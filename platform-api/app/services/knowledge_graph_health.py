"""Knowledge graph health checks and diagnostics."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AIProjectGraphSnapshot,
    KnowledgeGraph,
    KnowledgeGraphHealthCheck,
    KnowledgeGraphVersion,
    Project,
    ProjectBusinessContext,
)
from app.services.knowledge_graph_lifecycle import KnowledgeGraphLifecycleManager

logger = logging.getLogger(__name__)

HEALTHY = "healthy"
WARNING = "warning"
DEGRADED = "degraded"
STALE = "stale"
UNHEALTHY = "unhealthy"
UNAVAILABLE = "unavailable"


class KnowledgeGraphHealthService:
    """Run structural, source-alignment, and dependency health checks."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        lifecycle: KnowledgeGraphLifecycleManager | None = None,
    ) -> None:
        self.session = session
        self.lifecycle = lifecycle or KnowledgeGraphLifecycleManager(session)

    async def run_health_check(
        self,
        project_id: int,
        *,
        check_type: str = "on_demand",
    ) -> KnowledgeGraphHealthCheck:
        """Run a full health check for the project's active graph version."""
        project = await self.session.get(Project, project_id)
        if project is None:
            return self._unavailable(project_id, "Project not found", check_type)

        graph = await self.lifecycle.ensure_graph(project_id, reason="Health check")
        version = await self._load_version(graph.active_version_id or 0)

        started_at = datetime.now(UTC)
        hc = KnowledgeGraphHealthCheck(
            graph_id=graph.id,
            version_id=version.id if version else None,
            tenant_id=project.tenant_id,
            project_id=project_id,
            status="unknown",
            check_type=check_type,
            node_count=0,
            edge_count=0,
            disconnected_components=0,
            started_at=started_at,
        )

        if version is None:
            hc.status = UNAVAILABLE
            hc.completed_at = datetime.now(UTC)
            hc.errors = ["No active knowledge graph version"]
            self.session.add(hc)
            graph.last_health_check_at = datetime.now(UTC)
            return hc

        snapshot = await self.session.scalar(
            select(AIProjectGraphSnapshot).where(
                AIProjectGraphSnapshot.tenant_id == project.tenant_id,
                AIProjectGraphSnapshot.project_id == project_id,
                AIProjectGraphSnapshot.snapshot_key == version.storage_reference,
            )
        )
        if snapshot is None:
            hc.status = UNAVAILABLE
            hc.completed_at = datetime.now(UTC)
            hc.errors = ["Active version snapshot is missing"]
            self.session.add(hc)
            graph.last_health_check_at = datetime.now(UTC)
            graph.lifecycle_status = "degraded"
            return hc

        payload = snapshot.payload or {}
        full_graph = payload.get("fullGraph") or {}
        nodes = full_graph.get("nodes") or []
        edges = full_graph.get("edges") or []

        hc.node_count = len(nodes)
        hc.edge_count = len(edges)

        structural_checks = self._structural_checks(nodes, edges, version)
        source_alignment = await self._source_alignment(graph, version, project_id)
        dependency_checks = self._dependency_checks(nodes)

        hc.structural_checks = structural_checks
        hc.source_alignment = source_alignment
        hc.dependency_checks = dependency_checks
        hc.orphan_ratio = structural_checks.get("orphan_ratio")
        hc.disconnected_components = structural_checks.get(
            "disconnected_components", 0
        )
        hc.warnings = structural_checks.get("warnings", []) + source_alignment.get("warnings", [])
        hc.errors = structural_checks.get("errors", []) + source_alignment.get("errors", [])

        # Determine overall status.
        if structural_checks.get("errors") or source_alignment.get("errors"):
            hc.status = UNHEALTHY
        elif graph.lifecycle_status == "stale":
            hc.status = STALE
        elif dependency_checks.get("missing_executive_insight_nodes"):
            hc.status = DEGRADED
            hc.warnings = hc.warnings or []
            hc.warnings.append("Project context nodes missing for Executive Insight")
        elif structural_checks.get("warnings") or source_alignment.get("warnings"):
            hc.status = WARNING
        else:
            hc.status = HEALTHY

        hc.completed_at = datetime.now(UTC)
        self.session.add(hc)
        graph.last_health_check_at = datetime.now(UTC)
        if hc.status in (UNHEALTHY, DEGRADED):
            graph.lifecycle_status = hc.status if hc.status != UNHEALTHY else "degraded"
        return hc

    async def latest_health_status(self, project_id: int) -> str:
        hc = await self.session.scalar(
            select(KnowledgeGraphHealthCheck)
            .where(KnowledgeGraphHealthCheck.project_id == project_id)
            .order_by(KnowledgeGraphHealthCheck.completed_at.desc().nullslast())
        )
        return hc.status if hc else UNAVAILABLE

    def _structural_checks(
        self,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        version: KnowledgeGraphVersion,
    ) -> dict[str, Any]:
        errors: list[str] = []
        warnings: list[str] = []

        if not nodes:
            errors.append("Graph contains no nodes")

        project_nodes = [n for n in nodes if n.get("node_type") == "project"]
        if not project_nodes:
            errors.append("Missing required project hub node")
        elif len(project_nodes) > 1:
            warnings.append(f"Multiple project hub nodes found ({len(project_nodes)})")

        node_ids = {n.get("id") for n in nodes if n.get("id") is not None}
        edge_refs = set()
        dangling_edges = 0
        for e in edges:
            from_id = e.get("from_node_id")
            to_id = e.get("to_node_id")
            if from_id not in node_ids:
                dangling_edges += 1
            if to_id not in node_ids:
                dangling_edges += 1
            edge_refs.add(from_id)
            edge_refs.add(to_id)

        if dangling_edges:
            warnings.append(f"{dangling_edges} edge references point to missing nodes")

        orphan_ids = node_ids - edge_refs - {"project"}
        orphan_ratio = (len(orphan_ids) / len(nodes)) if nodes else 0.0
        if orphan_ratio > 0.5:
            warnings.append(f"High orphan ratio: {orphan_ratio:.2%}")

        disconnected = version.disconnected_component_count or 0
        if disconnected > 5:
            warnings.append(f"Many disconnected components: {disconnected}")

        return {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "project_node_count": len(project_nodes),
            "dangling_edge_refs": dangling_edges,
            "orphan_ratio": orphan_ratio,
            "orphan_count": len(orphan_ids),
            "disconnected_components": disconnected,
            "errors": errors,
            "warnings": warnings,
        }

    async def _source_alignment(
        self,
        graph: KnowledgeGraph,
        version: KnowledgeGraphVersion,
        project_id: int,
    ) -> dict[str, Any]:
        warnings: list[str] = []
        errors: list[str] = []

        if not version.source_fingerprint:
            warnings.append("Active version has no source fingerprint")
            return {"fingerprint_match": False, "errors": errors, "warnings": warnings}

        current = await self.lifecycle.compute_source_fingerprint(project_id)
        if current != version.source_fingerprint:
            warnings.append(
                f"Source fingerprint drift detected: expected {version.source_fingerprint[:16]}..., current {current[:16]}..."
            )
            if graph.lifecycle_status == "active":
                graph.lifecycle_status = "stale"

        settings = await self.session.scalar(
            select(ProjectBusinessContext).where(
                ProjectBusinessContext.project_id == project_id,
                ProjectBusinessContext.tenant_id == graph.tenant_id,
            )
        )
        context_enabled = settings.ai_context_enabled if settings else False
        if not context_enabled:
            warnings.append("Project business context is disabled; graph may be incomplete")

        return {
            "fingerprint_match": current == version.source_fingerprint,
            "active_fingerprint": version.source_fingerprint,
            "current_fingerprint": current,
            "context_enabled": context_enabled,
            "errors": errors,
            "warnings": warnings,
        }

    def _dependency_checks(self, nodes: list[dict[str, Any]]) -> dict[str, Any]:
        required = {"project", "metric", "risk"}
        present = {str(n.get("node_type")) for n in nodes}
        missing = sorted(required - present)
        return {
            "required_node_types": sorted(required),
            "present_node_types": sorted(present),
            "missing_executive_insight_nodes": missing,
        }

    def _unavailable(
        self,
        project_id: int,
        reason: str,
        check_type: str,
    ) -> KnowledgeGraphHealthCheck:
        hc = KnowledgeGraphHealthCheck(
            tenant_id=0,
            project_id=project_id,
            status=UNAVAILABLE,
            check_type=check_type,
            node_count=0,
            edge_count=0,
            disconnected_components=0,
            errors=[reason],
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        self.session.add(hc)
        return hc

    async def _load_version(self, version_id: int) -> KnowledgeGraphVersion | None:
        if not version_id:
            return None
        return await self.session.get(KnowledgeGraphVersion, version_id)
