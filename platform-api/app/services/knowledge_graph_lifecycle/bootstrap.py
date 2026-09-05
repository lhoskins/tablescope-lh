from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from app.models import (
    Dashboard,
    DatabaseDataSource,
    FileSourceMeta,
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
from app.models.reference_library import ReferenceDocument
from app.services.knowledge_graph_builder import (
    SNAPSHOT_PIPELINE_VERSION,
)
from app.services.knowledge_graph_context import active_reference_document_conditions

from .base import LifecycleBase

# KG-13/KG-44: the canonical set of graph-relevant sources -- both
# ``compute_source_fingerprint`` (staleness hashing) and
# ``current_source_watermark`` (checkpoint verification) iterate this same
# list, so the two can no longer silently diverge on which sources count.
#
# KG-14: the 5th element names the field(s) whose *content* -- not just id
# and updated_at -- must be folded into the fingerprint. IDs and timestamps
# alone miss a content edit that doesn't bump updated_at (a bad clock, an
# import that preserves timestamps, direct SQL). FileSourceMeta/ProjectAsset
# already store their own content hash (content_sha256/file_hash) computed
# from the actual file bytes -- reused verbatim rather than re-derived.
_FINGERPRINT_MODELS: list[tuple[Any, str, str, str, tuple[str, ...]]] = [
    (ProjectGoal, "goals", "id", "updated_at", ("title", "description", "category", "priority", "status")),
    (ProjectMetric, "metrics", "id", "updated_at", ("name", "description", "business_definition", "aggregation", "expression", "source_mapping")),
    (ProjectRisk, "risks", "id", "updated_at", ("title", "description", "mitigation", "contingency", "severity")),
    (DatabaseDataSource, "data_sources", "id", "updated_at", ("table_name", "schema_name")),
    (FileSourceMeta, "file_sources", "id", "updated_at", ("content_sha256",)),
    (SavedQuery, "saved_queries", "id", "updated_at", ("sql_text",)),
    (Dashboard, "dashboards", "id", "updated_at", ("config",)),
    (ProjectAsset, "assets", "id", "updated_at", ("file_hash",)),
]


def _content_hash(row: Any, fields: tuple[str, ...]) -> str:
    """Stable hash of the named fields' current values (KG-14)."""
    parts: list[str] = []
    for field in fields:
        value = getattr(row, field, None)
        if isinstance(value, dict | list):
            value = json.dumps(value, sort_keys=True, default=str)
        parts.append(str(value) if value is not None else "")
    combined = "\x1f".join(parts)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


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
            "file_sources": [],
            "saved_queries": [],
            "dashboards": [],
            "assets": [],
            "reference_documents": [],
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

        for model, key, id_attr, ts_attr, content_fields in _FINGERPRINT_MODELS:
            stmt = select(model).where(model.project_id == project_id)
            if hasattr(model, "tenant_id"):
                stmt = stmt.where(model.tenant_id == tenant_id)
            rows = (await self.session.scalars(stmt)).all()
            parts[key] = sorted(
                [
                    (
                        getattr(row, id_attr),
                        (getattr(row, ts_attr).isoformat() if getattr(row, ts_attr) else None),
                        _content_hash(row, content_fields),
                    )
                    for row in rows
                ],
                key=lambda x: x[0],
            )

        # Reference Library: same tier-based scope collect_structural_graph
        # uses (project docs, tenant-wide company docs, and global industry
        # standards) -- KG-13, so updating any of them (including one another
        # tenant/project's active industry standard) marks this project's
        # graph stale, matching what the collector actually pulls in.
        ref_rows = (
            await self.session.execute(
                select(ReferenceDocument.id, ReferenceDocument.updated_at).where(
                    *active_reference_document_conditions(tenant_id, project_id),
                )
            )
        ).all()
        parts["reference_documents"] = sorted(
            [(r[0], r[1].isoformat() if r[1] else None) for r in ref_rows],
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


    async def current_source_watermark(
        self, project_id: int, tenant_id: int,
    ) -> datetime | None:
        """KG-44: latest ``updated_at`` across every graph-relevant source.

        ``_verify_source_checkpoint`` previously only watched
        ``AIProjectGraphNode``/``AIProjectGraphEdge`` staging-table
        ``created_at`` -- a row *update* never bumps ``created_at`` (those
        tables have no ``updated_at`` column), and a change to any
        non-staging source (a goal/metric/risk edit, a file/query/dashboard
        rename, a reference-library update, a repository scan) was never
        watched at all, so a coalesced build could start before such a
        change was actually visible to the builder. This iterates the same
        source list ``compute_source_fingerprint`` hashes, so the two can't
        drift apart on which sources count as graph-relevant.
        """
        watermarks: list[datetime] = []

        for model, _key, _id_attr, ts_attr, _content_fields in _FINGERPRINT_MODELS:
            ts_col = getattr(model, ts_attr)
            stmt = select(func.max(ts_col)).where(model.project_id == project_id)
            if hasattr(model, "tenant_id"):
                stmt = stmt.where(model.tenant_id == tenant_id)
            ts = await self.session.scalar(stmt)
            if ts is not None:
                watermarks.append(ts)

        ref_ts = await self.session.scalar(
            select(func.max(ReferenceDocument.updated_at)).where(
                *active_reference_document_conditions(tenant_id, project_id),
            )
        )
        if ref_ts is not None:
            watermarks.append(ref_ts)

        scan_ts = await self.session.scalar(
            select(func.max(RepositoryScan.updated_at))
            .join(
                RepositoryConnection,
                RepositoryScan.connection_id == RepositoryConnection.id,
            )
            .where(
                RepositoryConnection.project_id == project_id,
                RepositoryConnection.tenant_id == tenant_id,
            )
        )
        if scan_ts is not None:
            watermarks.append(scan_ts)

        context_ts = await self.session.scalar(
            select(func.max(ProjectBusinessContext.updated_at)).where(
                ProjectBusinessContext.project_id == project_id,
                ProjectBusinessContext.tenant_id == tenant_id,
            )
        )
        if context_ts is not None:
            watermarks.append(context_ts)

        return max(watermarks) if watermarks else None


