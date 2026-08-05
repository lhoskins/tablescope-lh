from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, has_role
from app.models import (
    AIProjectGraphSnapshot,
    AuditEvent,
    KnowledgeGraph,
    KnowledgeGraphBuild,
    KnowledgeGraphVersion,
    Project,
    ProjectMember,
)
from app.services.knowledge_graph_builder import (
    _json_safe,
)

from .base import LifecycleBase
from .impact_analyzer import GraphImpactAnalyzer

logger = logging.getLogger(__name__)


MAX_VERSION_HISTORY = 20


BUILD_HEARTBEAT_TIMEOUT_SECONDS = 300


class KnowledgeGraphConcurrencyError(HTTPException):
    """Raised when an optimistic lock on the graph row fails."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail="Knowledge graph state changed during the operation; retry.",
        )


class StateMixin(LifecycleBase):
    """KnowledgeGraphLifecycleManager mixin."""
    def __init__(
        self,
        session: AsyncSession,
        context: RequestContext | None = None,
    ) -> None:
        self.session = session
        self.context = context
        self.impact_analyzer = GraphImpactAnalyzer()


    async def _require_project(
        self, project_id: int, *, write: bool = False
    ) -> Project:
        project = await self.session.get(Project, project_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
            )
        tenant_id = self.context.tenant_id if self.context else project.tenant_id
        if project.tenant_id != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
            )

        if not write:
            return project

        # No request context means a system-initiated call (worker task, event
        # trigger). Those are already tenant-scoped above and carry no user to
        # authorize, so they are allowed to schedule rebuilds.
        if self.context is None:
            return project

        user_id = self.context.user_id if self.context else None
        role = self.context.role if self.context else None
        if project.owner_id == user_id or has_role(role or "", Role.ADMIN):
            return project
        member = await self.session.scalar(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
                ProjectMember.is_active.is_(True),
            )
        )
        if member is not None and member.role in ("editor", "admin", "owner"):
            return project
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No access to this project"
        )


    async def _audit(
        self,
        *,
        project_id: int,
        event_type: str,
        title: str | None = None,
        prompt_type: str | None = None,
        tables: list[str] | None = None,
        documents: list[str] | None = None,
    ) -> None:
        tenant_id = self.context.tenant_id if self.context else None
        if tenant_id is None:
            project = await self.session.get(Project, project_id)
            if project:
                tenant_id = project.tenant_id
        if tenant_id is None:
            return
        self.session.add(
            AuditEvent(
                tenant_id=tenant_id,
                project_id=project_id,
                user_id=self.context.user_id if self.context else None,
                event_type=event_type,
                scope="knowledge_graph",
                title=title,
                prompt_type=prompt_type,
                tables_queried=tables or [],
                documents_read=documents or [],
            )
        )


    async def activate_version(self, graph_id: int, version_id: int) -> KnowledgeGraph:
        """Atomically activate a validated candidate version and supersede the prior active."""
        graph = await self.session.get(KnowledgeGraph, graph_id)
        if graph is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge graph not found"
            )

        version = await self.session.get(KnowledgeGraphVersion, version_id)
        if version is None or version.graph_id != graph_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Version not found"
            )

        previous_active_id = graph.active_version_id
        if previous_active_id:
            prev = await self.session.get(KnowledgeGraphVersion, previous_active_id)
            if prev is not None:
                prev.status = "superseded"
                prev.superseded_at = datetime.now(UTC)

        version.status = "active"
        version.activated_at = datetime.now(UTC)
        graph.active_version_id = version.id
        graph.last_healthy_version_id = version.id
        graph.lifecycle_status = "active"

        await self._audit(
            project_id=graph.project_id,
            event_type="knowledge_graph.version_activated",
            title=f"Activated version {version.version_number}",
            prompt_type=version.build_type,
        )
        return graph


    async def mark_stale(self, project_id: int, reason: str) -> KnowledgeGraph:
        """Mark the project's graph stale when source drift is detected."""
        graph = await self.ensure_graph(project_id, reason="Mark stale")
        if graph.lifecycle_status not in {"stale", "disabled"}:
            graph.lifecycle_status = "stale"
        await self._audit(
            project_id=project_id,
            event_type="knowledge_graph.marked_stale",
            title=reason,
        )
        return graph


    async def _version_number(self, version_id: int | None) -> int | None:
        if not version_id:
            return None
        v = await self.session.get(KnowledgeGraphVersion, version_id)
        return v.version_number if v else None


    async def recover_stale_builds(self, *, older_than_seconds: int = 600) -> list[int]:
        """Find builds stuck in queued/building/validating and mark them failed."""
        cutoff = datetime.now(UTC) - timedelta(seconds=older_than_seconds)
        builds = (
            await self.session.scalars(
                select(KnowledgeGraphBuild).where(
                    KnowledgeGraphBuild.status.in_(["queued", "building", "validating"]),
                    KnowledgeGraphBuild.heartbeat_at < cutoff,
                )
            )
        ).all()
        recovered: list[int] = []
        for build in builds:
            build.status = "failed"
            build.error_code = "stale_recovery"
            build.safe_error_message = "Build was recovered after heartbeat timeout"
            build.completed_at = datetime.now(UTC)
            build.heartbeat_at = datetime.now(UTC)
            recovered.append(build.id)
            graph = await self.session.get(KnowledgeGraph, build.graph_id)
            if graph and graph.lifecycle_status in ("building", "validating", "requested"):
                # Only degrade if no other build is still in flight for this
                # graph; a newer active build may have taken over since this
                # stale one got stuck.
                in_flight = await self.session.scalar(
                    select(func.count())
                    .select_from(KnowledgeGraphBuild)
                    .where(
                        KnowledgeGraphBuild.graph_id == build.graph_id,
                        KnowledgeGraphBuild.id != build.id,
                        KnowledgeGraphBuild.status.in_(
                            ["queued", "building", "validating"]
                        ),
                    )
                )
                if in_flight == 0:
                    graph.lifecycle_status = "degraded"
        return recovered


    async def evaluate_stale_graphs(self) -> list[int]:
        """Find graphs whose source fingerprint drifted and mark them stale."""
        graphs = (
            await self.session.scalars(
                select(KnowledgeGraph).where(KnowledgeGraph.enabled.is_(True))
            )
        ).all()
        marked: list[int] = []
        for graph in graphs:
            fingerprint = await self.compute_source_fingerprint(graph.project_id)
            if fingerprint != (graph.current_source_fingerprint or ""):
                await self.mark_stale(
                    graph.project_id,
                    f"Source fingerprint changed from {graph.current_source_fingerprint} to {fingerprint}",
                )
                graph.current_source_fingerprint = fingerprint
                marked.append(graph.project_id)
        return marked


    async def resolve_representative_user(self, project_id: int) -> int | None:
        """Pick a user id to attribute a headless build to (project owner).

        AI enrichment only runs when a build has a ``requested_by`` user, so
        system-triggered rebuilds borrow the project owner rather than silently
        producing structural-only snapshots with no insight cards.
        """
        project = await self.session.get(Project, project_id)
        return project.owner_id if project else None


    async def get_active_snapshot_payload(
        self, project_id: int
    ) -> dict[str, Any] | None:
        """Return the active version's snapshot payload, or None."""
        graph = await self.ensure_graph(project_id, reason="Read active snapshot")
        version = await self._load_version(graph.active_version_id or 0)
        if version is None or not version.storage_reference:
            return None
        snapshot = await self.session.scalar(
            select(AIProjectGraphSnapshot).where(
                AIProjectGraphSnapshot.tenant_id == graph.tenant_id,
                AIProjectGraphSnapshot.project_id == project_id,
                AIProjectGraphSnapshot.snapshot_key == version.storage_reference,
            )
        )
        if snapshot is None:
            return None
        return _json_safe(snapshot.payload)


