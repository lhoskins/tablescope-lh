"""Tests for the repository scanner orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.repositories.base import RepositoryConnector
from app.connectors.repositories.types import (
    ConnectionTestResult,
    RepositoryItem,
    RepositoryPage,
)
from app.models import RepositoryConnection, Tenant, User
from app.services.repository_scanner import RepositoryScanner, create_scan

pytestmark = pytest.mark.anyio


@dataclass
class _FakeConnector(RepositoryConnector):
    connector_type: str = "fake"
    pages: list[RepositoryPage] = field(default_factory=list)
    page_index: int = 0

    async def validate_config(self, config: dict[str, Any]) -> None:
        return

    async def test_connection(
        self,
        config: dict[str, Any],
        credentials: dict[str, Any],
    ) -> ConnectionTestResult:
        return ConnectionTestResult(success=True, checks=[])

    async def list_items(
        self,
        config: dict[str, Any],
        credentials: dict[str, Any],
        checkpoint: dict[str, Any] | None = None,
        page_size: int = 500,
    ) -> RepositoryPage:
        if self.page_index >= len(self.pages):
            return RepositoryPage(items=[], has_more=False)
        page = self.pages[self.page_index]
        self.page_index += 1
        return page


async def _seed_tenant_and_user(db_session: AsyncSession) -> tuple[Tenant, User]:
    tenant = Tenant(slug="repo-tenant", name="Repo Tenant")
    db_session.add(tenant)
    await db_session.flush()

    user = User(
        tenant_id=tenant.id,
        email="repo@test.com",
        external_id="repo-user",
        role="tenant_admin",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return tenant, user


async def _seed_connection(
    db_session: AsyncSession,
    tenant: Tenant,
    user: User,
    connector_type: str = "fake",
) -> RepositoryConnection:
    from app.services.crypto import encrypt_secret

    conn = RepositoryConnection(
        tenant_id=tenant.id,
        created_by=user.id,
        name="Test repository",
        connector_type=connector_type,
        config_json={"rootPath": r"\\server\share"},
        credential_id=None,
    )
    db_session.add(conn)
    await db_session.flush()

    # Store a fake credential for the connector to read.
    from app.models import ConnectorCredential

    cred = ConnectorCredential(
        tenant_id=tenant.id,
        created_by=user.id,
        connector_type=connector_type,
        display_name="fake cred",
        secret_encrypted=encrypt_secret('{"token":"x"}'),
    )
    db_session.add(cred)
    await db_session.flush()
    conn.credential_id = cred.id
    await db_session.flush()
    return conn


@pytest.fixture(autouse=True)
def _patch_redis_lock_and_heartbeat(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.repository_lock import RepositoryScanHeartbeat, RepositoryScanLock

    async def _acquire(self: RepositoryScanLock) -> bool:
        return True

    async def _release(self: RepositoryScanLock) -> None:
        return

    async def _refresh(self: RepositoryScanLock) -> bool:
        return True

    async def _beat(self: RepositoryScanHeartbeat) -> None:
        return

    async def _is_alive(self: RepositoryScanHeartbeat) -> bool:
        return True

    monkeypatch.setattr(RepositoryScanLock, "acquire", _acquire)
    monkeypatch.setattr(RepositoryScanLock, "release", _release)
    monkeypatch.setattr(RepositoryScanLock, "refresh", _refresh)
    monkeypatch.setattr(RepositoryScanHeartbeat, "beat", _beat)
    monkeypatch.setattr(RepositoryScanHeartbeat, "is_alive", _is_alive)


@pytest.fixture
def patch_fake_connector(monkeypatch: pytest.MonkeyPatch) -> Any:
    def _patch(pages: list[RepositoryPage]) -> _FakeConnector:
        fake = _FakeConnector(pages=pages)

        def _resolve(*args: Any, **kwargs: Any) -> RepositoryConnector:
            return fake

        from app.connectors.repositories import registry
        from app.services import repository_scanner as scanner_module

        monkeypatch.setattr(registry, "get_repository_connector", _resolve)
        monkeypatch.setattr(scanner_module, "get_repository_connector", _resolve)
        return fake

    return _patch


async def test_scan_creates_and_updates_items(
    db_session: AsyncSession,
    patch_fake_connector: Any,
) -> None:
    tenant, user = await _seed_tenant_and_user(db_session)
    conn = await _seed_connection(db_session, tenant, user, connector_type="fake")

    now = datetime.now(UTC)
    pages = [
        RepositoryPage(
            items=[
                RepositoryItem(
                    external_id="file-1",
                    name="a.pdf",
                    relative_path="a.pdf",
                    parent_path="/",
                    item_type="file",
                    size=100,
                    extension="pdf",
                    mime_type="application/pdf",
                    created_at=now,
                    modified_at=now,
                ),
            ],
            has_more=True,
        ),
        RepositoryPage(
            items=[
                RepositoryItem(
                    external_id="dir-1",
                    name="archive",
                    relative_path="archive",
                    parent_path="/",
                    item_type="directory",
                ),
            ],
            has_more=False,
        ),
    ]
    patch_fake_connector(pages)

    scan = await create_scan(db_session, tenant.id, conn.id, trigger_type="manual")
    scanner = RepositoryScanner(db_session)
    await scanner.scan(tenant.id, conn.id, scan.id)

    await db_session.refresh(scan)
    assert scan.status == "succeeded"
    assert scan.files_seen == 1
    assert scan.directories_seen == 1

    from app.models import RepositoryItem as RepositoryItemModel

    result = await db_session.execute(
        select(RepositoryItemModel).where(RepositoryItemModel.connection_id == conn.id)
    )
    items = result.scalars().all()
    assert len(items) == 2
    names = {i.name for i in items}
    assert names == {"a.pdf", "archive"}


async def test_scan_detects_changes_and_deletions(
    db_session: AsyncSession,
    patch_fake_connector: Any,
) -> None:
    tenant, user = await _seed_tenant_and_user(db_session)
    conn = await _seed_connection(db_session, tenant, user, connector_type="fake")

    from app.models import RepositoryItem as RepositoryItemModel

    existing = RepositoryItemModel(
        tenant_id=tenant.id,
        connection_id=conn.id,
        external_id="file-1",
        name="a.pdf",
        relative_path="a.pdf",
        parent_path="/",
        item_type="file",
        size=100,
        extension="pdf",
        mime_type="application/pdf",
        etag="old-etag",
        source_modified_at=datetime.now(UTC),
        last_seen_scan_id=-1,
        extraction_status="pending",
    )
    db_session.add(existing)
    await db_session.flush()

    now = datetime.now(UTC)
    pages = [
        RepositoryPage(
            items=[
                RepositoryItem(
                    external_id="file-1",
                    name="a.pdf",
                    relative_path="a.pdf",
                    parent_path="/",
                    item_type="file",
                    size=200,
                    extension="pdf",
                    mime_type="application/pdf",
                    etag="new-etag",
                    created_at=now,
                    modified_at=now,
                ),
            ],
            has_more=False,
        ),
    ]
    patch_fake_connector(pages)

    scan = await create_scan(db_session, tenant.id, conn.id, trigger_type="manual")
    scanner = RepositoryScanner(db_session)
    await scanner.scan(tenant.id, conn.id, scan.id)

    await db_session.refresh(existing)
    assert existing.size == 200
    assert existing.etag == "new-etag"
    assert existing.last_changed_scan_id == scan.id


async def test_scan_marks_missing_items_deleted(
    db_session: AsyncSession,
    patch_fake_connector: Any,
) -> None:
    tenant, user = await _seed_tenant_and_user(db_session)
    conn = await _seed_connection(db_session, tenant, user, connector_type="fake")

    from app.models import RepositoryItem as RepositoryItemModel

    existing = RepositoryItemModel(
        tenant_id=tenant.id,
        connection_id=conn.id,
        external_id="file-1",
        name="a.pdf",
        relative_path="a.pdf",
        parent_path="/",
        item_type="file",
        size=100,
        extension="pdf",
        mime_type="application/pdf",
        source_modified_at=datetime.now(UTC),
        last_seen_scan_id=-1,
        extraction_status="pending",
    )
    db_session.add(existing)
    await db_session.flush()

    pages = [RepositoryPage(items=[], has_more=False)]
    patch_fake_connector(pages)

    scan = await create_scan(db_session, tenant.id, conn.id, trigger_type="manual")
    scanner = RepositoryScanner(db_session)
    await scanner.scan(tenant.id, conn.id, scan.id)

    await db_session.refresh(existing)
    assert existing.is_deleted is True
    assert existing.deleted_at is not None
