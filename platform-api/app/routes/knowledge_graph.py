"""Knowledge graph lifecycle and Executive Insight dependency routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models import KnowledgeGraphHealthCheck
from app.schemas.knowledge_graph import (
    ExecutiveInsightDependencyRead,
    IncrementalRebuildRequest,
    KnowledgeGraphBuildRead,
    KnowledgeGraphHealthCheckRead,
    KnowledgeGraphRebuildResponse,
    KnowledgeGraphStatusRead,
    KnowledgeGraphVersionRead,
)
from app.services.executive_insight_dependencies import ExecutiveInsightDependencyService
from app.services.knowledge_graph_health import KnowledgeGraphHealthService
from app.services.knowledge_graph_lifecycle import KnowledgeGraphLifecycleManager
from app.tasks.workflows import (
    enqueue_rebuild_knowledge_graph,
    enqueue_run_knowledge_graph_health_check,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects/{project_id}/knowledge-graph", tags=["knowledge-graph"])


def _lifecycle(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> KnowledgeGraphLifecycleManager:
    return KnowledgeGraphLifecycleManager(session, context)


def _health(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> KnowledgeGraphHealthService:
    return KnowledgeGraphHealthService(session)


@router.get("/status", response_model=KnowledgeGraphStatusRead)
async def get_knowledge_graph_status(
    project_id: int,
    lifecycle: KnowledgeGraphLifecycleManager = Depends(_lifecycle),
) -> KnowledgeGraphStatusRead:
    """Return the current knowledge graph lifecycle status, builds, and versions."""
    data = await lifecycle.get_status(project_id)
    return KnowledgeGraphStatusRead.model_validate(data)


@router.post("/rebuild", response_model=KnowledgeGraphRebuildResponse)
async def request_full_rebuild(
    project_id: int,
    lifecycle: KnowledgeGraphLifecycleManager = Depends(_lifecycle),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> KnowledgeGraphRebuildResponse:
    """Queue a full knowledge graph rebuild for the project."""
    build, build_type = await lifecycle.request_full_rebuild(project_id)
    enqueued = False
    try:
        await enqueue_rebuild_knowledge_graph(build.id)
        enqueued = True
    except Exception as exc:
        logger.warning("Failed to enqueue full rebuild for build %s: %s", build.id, exc)

    await lifecycle.session.commit()
    await lifecycle.session.refresh(build)

    return KnowledgeGraphRebuildResponse(
        build=KnowledgeGraphBuildRead.model_validate(build),
        build_type=build_type,
        enqueued=enqueued,
    )


@router.post("/rebuild/incremental", response_model=KnowledgeGraphRebuildResponse)
async def request_incremental_rebuild(
    project_id: int,
    payload: IncrementalRebuildRequest,
    lifecycle: KnowledgeGraphLifecycleManager = Depends(_lifecycle),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> KnowledgeGraphRebuildResponse:
    """Analyze the supplied change set and queue an incremental or full rebuild."""
    build, build_type = await lifecycle.request_incremental_rebuild(
        project_id,
        change_set=[item.model_dump() for item in payload.change_set],
    )
    enqueued = False
    try:
        await enqueue_rebuild_knowledge_graph(build.id)
        enqueued = True
    except Exception as exc:
        logger.warning(
            "Failed to enqueue incremental rebuild for build %s: %s", build.id, exc
        )

    await lifecycle.session.commit()
    await lifecycle.session.refresh(build)

    return KnowledgeGraphRebuildResponse(
        build=KnowledgeGraphBuildRead.model_validate(build),
        build_type=build_type,
        enqueued=enqueued,
    )


@router.get("/builds", response_model=list[KnowledgeGraphBuildRead])
async def list_knowledge_graph_builds(
    project_id: int,
    lifecycle: KnowledgeGraphLifecycleManager = Depends(_lifecycle),
) -> list[KnowledgeGraphBuildRead]:
    """List recent knowledge graph builds for the project."""
    data = await lifecycle.get_status(project_id)
    return [KnowledgeGraphBuildRead.model_validate(b) for b in data["builds"]]


@router.get("/builds/{build_id}", response_model=KnowledgeGraphBuildRead)
async def get_knowledge_graph_build(
    project_id: int,
    build_id: int,
    lifecycle: KnowledgeGraphLifecycleManager = Depends(_lifecycle),
) -> KnowledgeGraphBuildRead:
    """Return a single build record."""
    from app.models import KnowledgeGraphBuild

    build = await lifecycle.session.get(KnowledgeGraphBuild, build_id)
    if build is None or build.project_id != project_id:
        raise HTTPException(status_code=404, detail="Build not found")
    return KnowledgeGraphBuildRead.model_validate(build)


@router.post("/health-check", response_model=KnowledgeGraphHealthCheckRead)
async def run_knowledge_graph_health_check(
    project_id: int,
    health: KnowledgeGraphHealthService = Depends(_health),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> KnowledgeGraphHealthCheckRead:
    """Run an on-demand health check and enqueue it via the worker."""
    hc = await health.run_health_check(project_id, check_type="on_demand")
    try:
        await enqueue_run_knowledge_graph_health_check(project_id)
    except Exception as exc:
        logger.warning("Failed to enqueue health check for project %s: %s", project_id, exc)
    await health.session.commit()
    await health.session.refresh(hc)
    return KnowledgeGraphHealthCheckRead.model_validate(hc)


@router.get("/health", response_model=KnowledgeGraphHealthCheckRead)
async def get_knowledge_graph_health(
    project_id: int,
    health: KnowledgeGraphHealthService = Depends(_health),
) -> KnowledgeGraphHealthCheckRead:
    """Return the latest health check result."""
    latest = await health.session.scalar(
        select(KnowledgeGraphHealthCheck)
        .where(KnowledgeGraphHealthCheck.project_id == project_id)
        .order_by(KnowledgeGraphHealthCheck.completed_at.desc().nullslast())
    )
    if latest is None:
        raise HTTPException(status_code=404, detail="No health check found")
    return KnowledgeGraphHealthCheckRead.model_validate(latest)


@router.get("/versions", response_model=list[KnowledgeGraphVersionRead])
async def list_knowledge_graph_versions(
    project_id: int,
    lifecycle: KnowledgeGraphLifecycleManager = Depends(_lifecycle),
) -> list[KnowledgeGraphVersionRead]:
    """List recent knowledge graph versions."""
    data = await lifecycle.get_status(project_id)
    return [KnowledgeGraphVersionRead.model_validate(v) for v in data["versions"]]


@router.get("/dependencies/executive-insight", response_model=ExecutiveInsightDependencyRead)
async def get_executive_insight_dependency(
    project_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> ExecutiveInsightDependencyRead:
    """Return Executive Insight readiness based on the active knowledge graph."""
    service = ExecutiveInsightDependencyService(session)
    dep = await service.check(project_id)
    return ExecutiveInsightDependencyRead(**dep)
