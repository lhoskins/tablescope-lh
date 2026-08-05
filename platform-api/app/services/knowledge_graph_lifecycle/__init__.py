"""Knowledge graph lifecycle manager, rebuild orchestration, and source fingerprinting."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KnowledgeGraphBuild

from .bootstrap import BootstrapMixin
from .impact_analyzer import GraphImpactAnalyzer
from .rebuild_execution import RebuildExecutionMixin
from .rebuild_request import RebuildRequestMixin
from .state import KnowledgeGraphConcurrencyError, StateMixin, logger
from .status import StatusMixin


class KnowledgeGraphLifecycleManager(
    StateMixin,
    BootstrapMixin,
    RebuildRequestMixin,
    RebuildExecutionMixin,
    StatusMixin,
):
    """Knowledge graph lifecycle manager, rebuild orchestration, and source fingerprinting."""
    pass

async def request_event_driven_rebuild(
    session: AsyncSession,
    *,
    project_id: int,
    change_set: list[dict[str, Any]],
    trigger: str,
    requested_by: int | None = None,
    source_checkpoint: datetime | None = None,
) -> KnowledgeGraphBuild | None:
    """Best-effort: request a rebuild for a data-change event and enqueue it.

    This is the single entry point every "project data changed" site calls
    (document processed, SaaS sync completed, project-wide reprocess). It runs
    headlessly (no request context), commits the build record, and enqueues the
    worker job. It never raises — a graph-lifecycle failure must not poison the
    data-change flow that triggered it. Returns the build, or ``None`` when the
    request could not be recorded.

    Ordering contract: call this only AFTER the underlying source rows
    (``ai_project_graph_nodes``/``ai_project_graph_edges``, staging tables) are
    committed, because the rebuild reads them; the graph is strictly a
    downstream consumer of document/relationship/family data, never a producer.
    """
    try:
        lifecycle = KnowledgeGraphLifecycleManager(session)
        if requested_by is None:
            requested_by = await lifecycle.resolve_representative_user(project_id)
        build, build_type = await lifecycle.request_incremental_rebuild(
            project_id,
            change_set=change_set,
            trigger=trigger,
            requested_by=requested_by,
            source_checkpoint=source_checkpoint,
        )
        await session.commit()
    except Exception:
        logger.exception(
            "Failed to record event-driven graph rebuild for project %s (%s)",
            project_id,
            trigger,
        )
        try:
            await session.rollback()
        except Exception:  # pragma: no cover - defensive
            pass
        return None

    # request_incremental_rebuild coalesces onto an already-queued build, so
    # this may re-enqueue an existing build id; the deterministic arq job id
    # in enqueue_rebuild_knowledge_graph makes that a no-op.
    try:
        from app.tasks.workflows import enqueue_rebuild_knowledge_graph

        await enqueue_rebuild_knowledge_graph(build.id)
    except Exception as exc:
        # Fail-open: the build row stays queued; the stale-build recovery cron
        # will surface it if no worker ever picks it up.
        logger.warning(
            "Failed to enqueue graph rebuild %s for project %s (%s): %s",
            build.id,
            project_id,
            trigger,
            exc,
        )
    logger.info(
        "Event-driven graph rebuild requested: project=%s build=%s type=%s trigger=%s",
        project_id,
        build.id,
        build_type,
        trigger,
    )
    return build


__all__ = [
    "KnowledgeGraphLifecycleManager",
    "request_event_driven_rebuild",
    "KnowledgeGraphConcurrencyError",
    "GraphImpactAnalyzer",
]
