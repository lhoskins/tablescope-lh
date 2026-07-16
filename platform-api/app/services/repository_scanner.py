"""Asynchronous repository scanning with change detection and profiling."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.repositories import get_repository_connector
from app.models import (
    AIGovernanceAuditEvent,
    ConnectorCredential,
    RepositoryConnection,
    RepositoryItem,
    RepositoryScan,
)
from app.services.ai_governance import ai_governance_service
from app.services.crypto import decrypt_secret
from app.services.project_ai_context import build_project_ai_context
from app.services.repository_lock import RepositoryScanHeartbeat, RepositoryScanLock
from app.services.repository_profiler import RepositoryProfiler

logger = logging.getLogger(__name__)


class RepositoryScannerError(Exception):
    """Scanner-level failure."""


class RepositoryScanner:
    """Orchestrates one repository scan through a connector."""

    def __init__(
        self,
        session: AsyncSession,
        worker_id: str | None = None,
        page_size: int = 500,
        heartbeat_seconds: int = 60,
    ) -> None:
        self.session = session
        self.worker_id = worker_id or str(uuid.uuid4())
        self.page_size = max(1, min(page_size, 5000))
        self.heartbeat_seconds = max(10, heartbeat_seconds)
        self.seen_ids: set[str] = set()
        self._items_processed = 0

    async def scan(
        self,
        tenant_id: int,
        connection_id: int,
        scan_id: int,
    ) -> RepositoryScan:
        scan = await self._get_scan(tenant_id, scan_id)
        if scan.status not in ("queued", "retrying"):
            raise RepositoryScannerError(f"Scan is not runnable: {scan.status}")

        connection = await self._get_connection(tenant_id, connection_id)
        if not connection.is_enabled:
            raise RepositoryScannerError("Repository connection is disabled")

        lock = RepositoryScanLock(connection_id)
        if not await lock.acquire():
            raise RepositoryScannerError("Another scan is already in progress for this connection")

        heartbeat = RepositoryScanHeartbeat(scan_id)
        try:
            scan.status = "running"
            scan.started_at = datetime.now(UTC)
            scan.worker_id = self.worker_id
            scan.retry_attempt += 1
            await self._persist()
            await heartbeat.beat()

            connector = get_repository_connector(connection.connector_type)
            credentials = await self._resolve_credentials(connection)
            await connector.validate_config(connection.config_json)

            # Load project business context for project-assigned connectors so
            # repository intelligence can be grounded in business goals, metrics,
            # and risks.  Stored on the scan and profile records for auditability.
            project_context_summary: dict[str, Any] | None = None
            project_context_version: int | None = None
            if connection.project_id is not None:
                try:
                    ctx = await build_project_ai_context(
                        self.session,
                        tenant_id=tenant_id,
                        project_id=connection.project_id,
                        request_type="repository_intelligence",
                    )
                    project_context_summary = {
                        "project": ctx.get("project"),
                        "ai_context_enabled": ctx.get("ai_context_enabled"),
                        "goals": [g.get("title") for g in (ctx.get("goals") or [])[:10]],
                        "metrics": [m.get("name") for m in (ctx.get("metrics") or [])[:10]],
                        "risks": [r.get("title") for r in (ctx.get("risks") or [])[:10]],
                        "generated_at": ctx.get("generated_at"),
                    }
                    project_context_version = ctx.get("version")
                    scan.project_context_summary = project_context_summary
                    scan.project_context_version = project_context_version
                except Exception as exc:
                    logger.warning(
                        "Failed to build project context for repository scan %s: %s",
                        scan_id,
                        exc,
                    )

            # Governance pre-check: metadata scanning proceeds even if document
            # synthesis is disabled, but extraction must be gated.
            governance = await ai_governance_service.evaluate_method(
                self.session,
                tenant_id,
                "document_synthesis",
                project_id=connection.project_id,
            )
            extraction_allowed = governance.allowed
            if not extraction_allowed:
                await self._audit(
                    tenant_id=tenant_id,
                    event_type="repository.extraction_governance_blocked",
                    connection_id=connection.id,
                    scan_id=scan.id,
                    details={
                        "governance_allowed": governance.allowed,
                        "governance_reason_code": governance.reason_code,
                    },
                )

            checkpoint = scan.checkpoint_json
            while True:
                page = await connector.list_items(
                    connection.config_json,
                    credentials,
                    checkpoint=checkpoint,
                    page_size=self.page_size,
                )
                await self._upsert_items(
                    page.items,
                    tenant_id,
                    connection_id,
                    scan.id,
                    extraction_allowed,
                )
                await self._update_counts(scan, page.items)
                self._items_processed += len(page.items)

                if self._items_processed % 1000 < self.page_size:
                    await heartbeat.beat()
                    scan.heartbeat_at = datetime.now(UTC)

                checkpoint = page.checkpoint
                scan.checkpoint_json = checkpoint
                await self._persist()

                if not page.has_more:
                    break

            # Mark items not seen in this scan as deleted.
            await self._mark_deletions(tenant_id, connection_id, scan.id)

            # Build and store profile.
            await RepositoryProfiler.build_profile(
                self.session,
                connection_id,
                scan.id,
                tenant_id,
                project_context_summary=project_context_summary,
                project_context_version=project_context_version,
            )

            scan.status = "succeeded" if scan.error_count == 0 else "partial"
            scan.completed_at = datetime.now(UTC)
            connection.last_scan_id = scan.id
            connection.last_successful_scan_at = datetime.now(UTC)
            connection.status = "active"
            await self._persist()

            await self._audit(
                tenant_id=tenant_id,
                event_type="repository.scan.completed",
                connection_id=connection.id,
                scan_id=scan.id,
                details={
                    "status": scan.status,
                    "files_seen": scan.files_seen,
                    "directories_seen": scan.directories_seen,
                    "added": scan.added_count,
                    "changed": scan.changed_count,
                    "deleted": scan.deleted_count,
                },
            )

        except Exception as exc:
            logger.exception("Repository scan %s failed", scan_id)
            scan.status = "failed"
            scan.error_code = exc.__class__.__name__
            scan.error_message = str(exc)[:2000]
            scan.completed_at = datetime.now(UTC)
            connection.status = "error"
            await self._persist()

            await self._audit(
                tenant_id=tenant_id,
                event_type="repository.scan.failed",
                connection_id=connection_id,
                scan_id=scan.id,
                details={"error_code": scan.error_code, "error_message": scan.error_message},
            )
            raise RepositoryScannerError(scan.error_message) from exc
        finally:
            await lock.release()

        return scan

    async def _get_scan(
        self,
        tenant_id: int,
        scan_id: int,
    ) -> RepositoryScan:
        result = await self.session.execute(
            select(RepositoryScan).where(
                RepositoryScan.id == scan_id,
                RepositoryScan.tenant_id == tenant_id,
            )
        )
        scan = result.scalar_one_or_none()
        if scan is None:
            raise RepositoryScannerError("Scan not found")
        return scan

    async def _get_connection(
        self,
        tenant_id: int,
        connection_id: int,
    ) -> RepositoryConnection:
        result = await self.session.execute(
            select(RepositoryConnection).where(
                RepositoryConnection.id == connection_id,
                RepositoryConnection.tenant_id == tenant_id,
            )
        )
        connection = result.scalar_one_or_none()
        if connection is None:
            raise RepositoryScannerError("Repository connection not found")
        return connection

    async def _resolve_credentials(
        self,
        connection: RepositoryConnection,
    ) -> dict[str, Any]:
        if not connection.credential_id:
            raise RepositoryScannerError("Repository connector has no stored credentials")
        credential = await self.session.get(ConnectorCredential, connection.credential_id)
        if credential is None or credential.tenant_id != connection.tenant_id:
            raise RepositoryScannerError("Connector credential not found")
        if not credential.secret_encrypted:
            raise RepositoryScannerError("Connector credential is empty")
        try:
            return json.loads(decrypt_secret(credential.secret_encrypted))
        except Exception as exc:
            raise RepositoryScannerError("Unable to decrypt repository credentials") from exc

    async def _upsert_items(
        self,
        items: list[Any],
        tenant_id: int,
        connection_id: int,
        scan_id: int,
        extraction_allowed: bool,
    ) -> None:
        for item in items:
            self.seen_ids.add(item.external_id)

            result = await self.session.execute(
                select(RepositoryItem).where(
                    RepositoryItem.connection_id == connection_id,
                    RepositoryItem.external_id == item.external_id,
                    RepositoryItem.tenant_id == tenant_id,
                )
            )
            existing = result.scalar_one_or_none()

            extraction_status = "pending"
            if not extraction_allowed:
                extraction_status = "governance_blocked"
            elif not self._extraction_supported(item):
                extraction_status = "skipped"

            if existing is None:
                new_item = RepositoryItem(
                    tenant_id=tenant_id,
                    connection_id=connection_id,
                    external_id=item.external_id,
                    relative_path=item.relative_path,
                    name=item.name,
                    parent_path=item.parent_path or "/",
                    item_type=item.item_type,
                    extension=item.extension,
                    mime_type=item.mime_type,
                    size=item.size,
                    source_created_at=item.created_at,
                    source_modified_at=item.modified_at,
                    etag=item.etag,
                    content_hash=item.content_hash,
                    metadata_json=item.metadata,
                    first_seen_scan_id=scan_id,
                    last_seen_scan_id=scan_id,
                    last_changed_scan_id=scan_id,
                    extraction_status=extraction_status,
                )
                self.session.add(new_item)
                scan = await self._get_scan(tenant_id, scan_id)
                scan.added_count += 1
            else:
                changed = (
                    existing.etag != item.etag
                    or existing.content_hash != item.content_hash
                    or existing.source_modified_at != item.modified_at
                )

                existing.relative_path = item.relative_path
                existing.name = item.name
                existing.parent_path = item.parent_path or "/"
                existing.item_type = item.item_type
                existing.extension = item.extension
                existing.mime_type = item.mime_type
                existing.size = item.size
                existing.source_created_at = item.created_at
                existing.source_modified_at = item.modified_at
                existing.etag = item.etag
                existing.content_hash = item.content_hash
                existing.metadata_json = item.metadata
                existing.last_seen_scan_id = scan_id
                existing.is_deleted = False
                existing.deleted_at = None

                if changed:
                    existing.last_changed_scan_id = scan_id
                    scan = await self._get_scan(tenant_id, scan_id)
                    scan.changed_count += 1

                if existing.extraction_status == "pending" and not extraction_allowed:
                    existing.extraction_status = "governance_blocked"
                elif existing.extraction_status in ("pending", "governance_blocked") and extraction_allowed:
                    existing.extraction_status = extraction_status

    async def _mark_deletions(
        self,
        tenant_id: int,
        connection_id: int,
        scan_id: int,
    ) -> None:
        result = await self.session.execute(
            select(RepositoryItem).where(
                RepositoryItem.connection_id == connection_id,
                RepositoryItem.tenant_id == tenant_id,
                RepositoryItem.is_deleted.is_(False),
                RepositoryItem.last_seen_scan_id != scan_id,
            )
        )
        stale = result.scalars().all()
        for item in stale:
            item.is_deleted = True
            item.deleted_at = datetime.now(UTC)
        scan = await self._get_scan(tenant_id, scan_id)
        scan.deleted_count += len(stale)

    async def _update_counts(self, scan: RepositoryScan, items: list[Any]) -> None:
        for item in items:
            if item.item_type == "file":
                scan.files_seen += 1
                if isinstance(item.size, int):
                    scan.bytes_seen += item.size
            elif item.item_type == "directory":
                scan.directories_seen += 1

    def _extraction_supported(self, item: Any) -> bool:
        supported_exts = {
            "pdf",
            "txt",
            "md",
            "docx",
            "pptx",
            "xlsx",
            "csv",
            "json",
            "html",
        }
        return item.item_type == "file" and (item.extension or "").lower() in supported_exts

    async def _persist(self) -> None:
        await self.session.flush()

    async def _audit(
        self,
        *,
        tenant_id: int,
        event_type: str,
        connection_id: int,
        scan_id: int,
        details: dict[str, Any],
        actor_user_id: int | None = None,
    ) -> None:
        audit = AIGovernanceAuditEvent(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            actor_type="system",
            event_type=event_type,
            project_id=None,
            details={"connection_id": connection_id, "scan_id": scan_id, **details},
        )
        self.session.add(audit)
        await self.session.flush()


async def create_scan(
    session: AsyncSession,
    tenant_id: int,
    connection_id: int,
    trigger_type: str = "manual",
) -> RepositoryScan:
    scan = RepositoryScan(
        tenant_id=tenant_id,
        connection_id=connection_id,
        trigger_type=trigger_type,
        status="queued",
    )
    session.add(scan)
    await session.flush()
    return scan


async def list_scans(
    session: AsyncSession,
    tenant_id: int,
    connection_id: int,
) -> list[dict[str, Any]]:
    result = await session.execute(
        select(RepositoryScan)
        .where(
            RepositoryScan.tenant_id == tenant_id,
            RepositoryScan.connection_id == connection_id,
        )
        .order_by(RepositoryScan.created_at.desc())
    )
    return [s.to_summary_dict() for s in result.scalars().all()]


async def get_scan(
    session: AsyncSession,
    tenant_id: int,
    connection_id: int,
    scan_id: int,
) -> dict[str, Any]:
    result = await session.execute(
        select(RepositoryScan).where(
            RepositoryScan.id == scan_id,
            RepositoryScan.connection_id == connection_id,
            RepositoryScan.tenant_id == tenant_id,
        )
    )
    scan = result.scalar_one_or_none()
    if scan is None:
        raise RepositoryScannerError("Scan not found")
    return scan.to_summary_dict()


async def list_items(
    session: AsyncSession,
    tenant_id: int,
    connection_id: int,
    *,
    item_type: str | None = None,
    is_deleted: bool | None = False,
    extraction_status: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    where = [
        RepositoryItem.tenant_id == tenant_id,
        RepositoryItem.connection_id == connection_id,
    ]
    if item_type is not None:
        where.append(RepositoryItem.item_type == item_type)
    if is_deleted is not None:
        where.append(RepositoryItem.is_deleted.is_(is_deleted))
    if extraction_status:
        where.append(RepositoryItem.extraction_status == extraction_status)
    if search:
        like = f"%{search}%"
        where.append(
            (RepositoryItem.name.ilike(like))
            | (RepositoryItem.relative_path.ilike(like))
        )

    count_result = await session.execute(
        select(func.count(RepositoryItem.id)).where(*where)
    )
    total = count_result.scalar() or 0

    result = await session.execute(
        select(RepositoryItem)
        .where(*where)
        .order_by(RepositoryItem.relative_path)
        .limit(limit)
        .offset(offset)
    )
    items = result.scalars().all()
    return [i.to_dict() for i in items], total
