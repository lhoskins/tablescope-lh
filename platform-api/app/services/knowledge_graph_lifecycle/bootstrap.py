from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import func, select

from app.models import (
    Dashboard,
    DatabaseDataSource,
    KnowledgeGraph,
    KnowledgeGraphVersion,
    Project,
    ProjectAsset,
    ProjectBusinessContext,
    ProjectGoal,
    ProjectMetric,
    ProjectRisk,
    RepositoryConnection,
    RepositoryScan,
    SavedQuery,
)
from app.services.knowledge_graph_builder import (
    SNAPSHOT_PIPELINE_VERSION,
)

from .base import LifecycleBase


class BootstrapMixin(LifecycleBase):
    """KnowledgeGraphLifecycleManager mixin."""
    async def ensure_graph(
        self,
        project_id: int,
        *,
        reason: str | None = None,
    ) -> KnowledgeGraph:
        """Return the project's ``KnowledgeGraph`` row, creating it lazily."""
        project = await self._require_project(project_id)
        graph = await self.session.scalar(
            select(KnowledgeGraph).where(
                KnowledgeGraph.tenant_id == project.tenant_id,
                KnowledgeGraph.project_id == project_id,
            )
        )
        if graph is None:
            graph = KnowledgeGraph(
                tenant_id=project.tenant_id,
                project_id=project_id,
                lifecycle_status="missing",
                enabled=True,
                version=0,
            )
            self.session.add(graph)
            await self.session.flush()
            await self._audit(
                project_id=project_id,
                event_type="knowledge_graph.ensure_graph",
                title=reason or "Graph row initialized",
            )
        return graph


    async def _next_version_number(self, project_id: int) -> int:
        result = await self.session.scalar(
            select(func.coalesce(func.max(KnowledgeGraphVersion.version_number), 0)).where(
                KnowledgeGraphVersion.project_id == project_id
            )
        )
        return int(result or 0) + 1


    async def _load_version(self, version_id: int) -> KnowledgeGraphVersion | None:
        return await self.session.get(KnowledgeGraphVersion, version_id)


    async def compute_source_fingerprint(self, project_id: int) -> str:
        """Compute a deterministic fingerprint of all graph-relevant sources."""
        project = await self.session.get(Project, project_id)
        tenant_id = project.tenant_id if project else 0

        parts: dict[str, Any] = {
            "project_version": 0,
            "goals": [],
            "metrics": [],
            "risks": [],
            "data_sources": [],
            "saved_queries": [],
            "dashboards": [],
            "assets": [],
            "repository_scans": [],
            "pipeline_version": SNAPSHOT_PIPELINE_VERSION,
        }

        settings = await self.session.scalar(
            select(ProjectBusinessContext).where(
                ProjectBusinessContext.tenant_id == tenant_id,
                ProjectBusinessContext.project_id == project_id,
            )
        )
        if settings:
            parts["project_version"] = settings.version

        fingerprint_models: list[tuple[Any, str, str, str]] = [
            (ProjectGoal, "goals", "id", "updated_at"),
            (ProjectMetric, "metrics", "id", "updated_at"),
            (ProjectRisk, "risks", "id", "updated_at"),
            (DatabaseDataSource, "data_sources", "id", "updated_at"),
            (SavedQuery, "saved_queries", "id", "updated_at"),
            (Dashboard, "dashboards", "id", "updated_at"),
            (ProjectAsset, "assets", "id", "updated_at"),
        ]
        for model, key, id_attr, ts_attr in fingerprint_models:
            id_col = getattr(model, id_attr)
            ts_col = getattr(model, ts_attr)
            stmt = select(id_col, ts_col).where(model.project_id == project_id)
            if hasattr(model, "tenant_id"):
                stmt = stmt.where(model.tenant_id == tenant_id)
            rows = (await self.session.execute(stmt)).all()
            parts[key] = sorted(
                [
                    (r[0], r[1].isoformat() if r[1] else None)
                    for r in rows
                ],
                key=lambda x: x[0],
            )

        conn_ids = (
            await self.session.scalars(
                select(RepositoryConnection.id).where(
                    RepositoryConnection.project_id == project_id,
                    RepositoryConnection.tenant_id == tenant_id,
                )
            )
        ).all()
        for conn_id in conn_ids:
            scan = await self.session.scalar(
                select(RepositoryScan)
                .where(RepositoryScan.connection_id == conn_id)
                .order_by(RepositoryScan.id.desc())
            )
            parts["repository_scans"].append(
                (conn_id, scan.id if scan else None, scan.updated_at.isoformat() if scan and scan.updated_at else None)
            )

        serialized = json.dumps(parts, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


