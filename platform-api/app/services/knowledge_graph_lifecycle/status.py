from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.models import (
    KnowledgeGraphBuild,
    KnowledgeGraphHealthCheck,
    KnowledgeGraphVersion,
)

from .base import LifecycleBase
from .state import MAX_VERSION_HISTORY


class StatusMixin(LifecycleBase):
    """KnowledgeGraphLifecycleManager mixin."""
    async def get_status(self, project_id: int) -> dict[str, Any]:
        """Return a status snapshot with builds, versions, and latest health."""
        graph = await self.ensure_graph(project_id, reason="Status check")
        versions = (
            await self.session.scalars(
                select(KnowledgeGraphVersion)
                .where(
                    KnowledgeGraphVersion.project_id == project_id,
                    KnowledgeGraphVersion.tenant_id == graph.tenant_id,
                )
                .order_by(KnowledgeGraphVersion.version_number.desc())
                .limit(MAX_VERSION_HISTORY)
            )
        ).all()
        builds = (
            await self.session.scalars(
                select(KnowledgeGraphBuild)
                .where(
                    KnowledgeGraphBuild.project_id == project_id,
                    KnowledgeGraphBuild.tenant_id == graph.tenant_id,
                )
                .order_by(KnowledgeGraphBuild.id.desc())
                .limit(MAX_VERSION_HISTORY)
            )
        ).all()
        latest_health = await self.session.scalar(
            select(KnowledgeGraphHealthCheck)
            .where(
                KnowledgeGraphHealthCheck.project_id == project_id,
                KnowledgeGraphHealthCheck.tenant_id == graph.tenant_id,
            )
            .order_by(KnowledgeGraphHealthCheck.completed_at.desc().nullslast())
        )

        active_version = await self._load_version(graph.active_version_id or 0)
        active_node_count = 0
        active_edge_count = 0
        if active_version:
            active_node_count = active_version.node_count
            active_edge_count = active_version.edge_count

        return {
            "project_id": project_id,
            "graph_id": graph.id,
            "lifecycle_status": graph.lifecycle_status,
            "enabled": graph.enabled,
            "active_version_id": graph.active_version_id,
            "active_version_number": active_version.version_number if active_version else None,
            "last_healthy_version_id": graph.last_healthy_version_id,
            "last_healthy_version_number": (
                await self._version_number(graph.last_healthy_version_id)
            ),
            "current_source_fingerprint": graph.current_source_fingerprint,
            "active_source_fingerprint": active_version.source_fingerprint if active_version else None,
            "last_successful_build_at": graph.last_successful_build_at,
            "last_health_check_at": graph.last_health_check_at,
            "active_node_count": active_node_count,
            "active_edge_count": active_edge_count,
            "health_status": latest_health.status if latest_health else "unknown",
            "has_active_version": active_version is not None,
            "versions": list(versions),
            "builds": list(builds),
        }


