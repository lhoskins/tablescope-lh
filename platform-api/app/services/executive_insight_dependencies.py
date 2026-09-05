"""Executive Insight dependency readiness for the project knowledge graph."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KnowledgeGraphVersion
from app.services.knowledge_graph_health import (
    DEGRADED,
    STALE,
    UNAVAILABLE,
    KnowledgeGraphHealthService,
    )
from app.services.knowledge_graph_lifecycle import KnowledgeGraphLifecycleManager

logger = logging.getLogger(__name__)


class ExecutiveInsightDependencyService:
    """Check whether the knowledge graph is ready to support Executive Insight."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        lifecycle: KnowledgeGraphLifecycleManager | None = None,
        health: KnowledgeGraphHealthService | None = None,
    ) -> None:
        self.session = session
        self.lifecycle = lifecycle or KnowledgeGraphLifecycleManager(session)
        self.health = health or KnowledgeGraphHealthService(
            session, lifecycle=self.lifecycle
        )

    async def check(self, project_id: int) -> dict[str, Any]:
        """Return a readiness verdict for Executive Insight.

        Modes:
        - ``full``: graph is active, healthy, and aligned with sources.
        - ``limited``: graph is available but stale/degraded; insight is allowed
          with a disclosure but may be incomplete.
        - ``blocked``: graph is missing/unhealthy and insight generation is unsafe.
        """
        graph = await self.lifecycle.ensure_graph(project_id, reason="Executive Insight dependency check")
        version = await self.session.get(
            KnowledgeGraphVersion, graph.active_version_id or 0
        )
        active_node_count = version.node_count if version else 0
        active_edge_count = version.edge_count if version else 0

        # Re-run a lightweight health check so the verdict is always current.
        hc = await self.health.run_health_check(
            project_id, check_type="pre_executive_insight"
        )

        warnings = list(hc.warnings or [])
        errors = list(hc.errors or [])
        blocking_reasons: list[str] = []

        # A missing graph is not a hard block — Executive Insight can still run in
        # limited mode with a disclosure so existing projects remain usable while
        # the graph is being built.
        if version is None or not version.storage_reference:
            warnings.append("No active knowledge graph version")
            # Health check returns "unavailable" errors for a missing graph;
            # treat those as limited-mode warnings, not blockers.
            errors = []

        if graph.lifecycle_status == "disabled" or not graph.enabled:
            blocking_reasons.append("Knowledge graph is disabled")

        if errors:
            blocking_reasons.extend(errors)

        missing = (hc.dependency_checks or {}).get(
            "missing_executive_insight_nodes", []
        )
        if missing:
            warnings.append(f"Missing graph nodes for Executive Insight: {', '.join(missing)}")

        # Determine mode.
        if blocking_reasons:
            mode = "blocked"
            ready = False
        elif (
            graph.lifecycle_status in (STALE, DEGRADED)
            or hc.status != "healthy"
            or graph.lifecycle_status in (UNAVAILABLE, "missing")
        ):
            mode = "limited"
            ready = True
        else:
            mode = "full"
            ready = True

        disclosure = ""
        if mode == "blocked":
            disclosure = (
                "Executive Insight is blocked because the knowledge graph is not ready. "
                "Run a full rebuild from the Knowledge Graph settings page."
            )
        elif mode == "limited":
            disclosure = (
                "Executive Insight is available in limited mode: the graph is stale or "
                "degraded. Results may be incomplete."
            )

        return {
            "ready": ready,
            "mode": mode,
            "graph_status": graph.lifecycle_status,
            "graph_version_id": graph.active_version_id,
            "graph_version_number": version.version_number if version else None,
            "active_node_count": active_node_count,
            "active_edge_count": active_edge_count,
            "warnings": warnings,
            "blocking_reasons": blocking_reasons,
            "disclosure": disclosure,
            "health_status": hc.status,
        }
