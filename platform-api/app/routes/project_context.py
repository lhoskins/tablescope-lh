"""Project business context routes — goals, metrics, targets, risks, settings, audit."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.schemas.project_context import (
    KpiSourceMatchJobCreate,
    KpiSourceMatchJobRead,
    ProjectBusinessContextRead,
    ProjectBusinessContextUpdate,
    ProjectContextAuditEventRead,
    ProjectContextAuditList,
    ProjectContextRead,
    ProjectGoalCreate,
    ProjectGoalRead,
    ProjectGoalUpdate,
    ProjectMetricCreate,
    ProjectMetricRead,
    ProjectMetricTargetCreate,
    ProjectMetricTargetRead,
    ProjectMetricTargetUpdate,
    ProjectMetricUpdate,
    ProjectRiskCreate,
    ProjectRiskRead,
    ProjectRiskUpdate,
    ReorderRequest,
)
from app.services.project_context import ProjectContextService
from app.tasks.kpi_source_matching import enqueue_match_kpi_data_source

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects", tags=["project-context"])


def _service(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> ProjectContextService:
    return ProjectContextService(session, context)


@router.get("/{project_id}/context", response_model=ProjectContextRead)
async def get_project_context(
    project_id: int,
    service: ProjectContextService = Depends(_service),
) -> ProjectContextRead:
    """Return the full project business context (settings, goals, metrics, risks)."""
    data = await service.get_full_context(project_id)
    return ProjectContextRead.model_validate(data)


@router.put("/{project_id}/context/settings", response_model=ProjectBusinessContextRead)
async def update_project_settings(
    project_id: int,
    payload: ProjectBusinessContextUpdate,
    service: ProjectContextService = Depends(_service),
) -> ProjectBusinessContextRead:
    """Update project business-context settings."""
    settings = await service.update_settings(project_id, payload)
    return ProjectBusinessContextRead.model_validate(settings)


# ── Goals ─────────────────────────────────────────────────────────────────


@router.get("/{project_id}/goals", response_model=list[ProjectGoalRead])
async def list_goals(
    project_id: int,
    service: ProjectContextService = Depends(_service),
) -> list[ProjectGoalRead]:
    goals = await service.list_goals(project_id)
    return [ProjectGoalRead.model_validate(g) for g in goals]


@router.post("/{project_id}/goals", response_model=ProjectGoalRead, status_code=status.HTTP_201_CREATED)
async def create_goal(
    project_id: int,
    payload: ProjectGoalCreate,
    service: ProjectContextService = Depends(_service),
) -> ProjectGoalRead:
    goal = await service.create_goal(project_id, payload)
    return ProjectGoalRead.model_validate(goal)


@router.patch("/{project_id}/goals/{goal_id}", response_model=ProjectGoalRead)
async def update_goal(
    project_id: int,
    goal_id: int,
    payload: ProjectGoalUpdate,
    service: ProjectContextService = Depends(_service),
) -> ProjectGoalRead:
    goal = await service.update_goal(project_id, goal_id, payload)
    return ProjectGoalRead.model_validate(goal)


@router.delete("/{project_id}/goals/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_goal(
    project_id: int,
    goal_id: int,
    service: ProjectContextService = Depends(_service),
) -> Response:
    await service.delete_goal(project_id, goal_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/{project_id}/goals/reorder")
async def reorder_goals(
    project_id: int,
    payload: ReorderRequest,
    service: ProjectContextService = Depends(_service),
) -> dict:
    await service.reorder_goals(project_id, payload)
    return {"ok": True}


# ── Metrics ─────────────────────────────────────────────────────────────────


@router.get("/{project_id}/metrics", response_model=list[ProjectMetricRead])
async def list_metrics(
    project_id: int,
    service: ProjectContextService = Depends(_service),
) -> list[ProjectMetricRead]:
    metrics = await service.list_metrics(project_id)
    return [ProjectMetricRead.model_validate(m) for m in metrics]


@router.post("/{project_id}/metrics", response_model=ProjectMetricRead, status_code=status.HTTP_201_CREATED)
async def create_metric(
    project_id: int,
    payload: ProjectMetricCreate,
    service: ProjectContextService = Depends(_service),
) -> ProjectMetricRead:
    metric = await service.create_metric(project_id, payload)
    # Eager load targets after creation so the read model can validate them.
    await service.session.refresh(metric, attribute_names=["targets"])
    return ProjectMetricRead.model_validate(metric)


@router.patch("/{project_id}/metrics/{metric_id}", response_model=ProjectMetricRead)
async def update_metric(
    project_id: int,
    metric_id: int,
    payload: ProjectMetricUpdate,
    service: ProjectContextService = Depends(_service),
) -> ProjectMetricRead:
    metric = await service.update_metric(project_id, metric_id, payload)
    await service.session.refresh(metric, attribute_names=["targets"])
    return ProjectMetricRead.model_validate(metric)


@router.delete("/{project_id}/metrics/{metric_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_metric(
    project_id: int,
    metric_id: int,
    service: ProjectContextService = Depends(_service),
) -> Response:
    await service.delete_metric(project_id, metric_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/{project_id}/metrics/reorder")
async def reorder_metrics(
    project_id: int,
    payload: ReorderRequest,
    service: ProjectContextService = Depends(_service),
) -> dict:
    await service.reorder_metrics(project_id, payload)
    return {"ok": True}


# ── Targets ─────────────────────────────────────────────────────────────────


@router.post(
    "/{project_id}/metrics/{metric_id}/targets",
    response_model=ProjectMetricTargetRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_target(
    project_id: int,
    metric_id: int,
    payload: ProjectMetricTargetCreate,
    service: ProjectContextService = Depends(_service),
) -> ProjectMetricTargetRead:
    target = await service.create_target(project_id, metric_id, payload)
    return ProjectMetricTargetRead.model_validate(target)


@router.patch("/{project_id}/metrics/{metric_id}/targets/{target_id}", response_model=ProjectMetricTargetRead)
async def update_target(
    project_id: int,
    metric_id: int,
    target_id: int,
    payload: ProjectMetricTargetUpdate,
    service: ProjectContextService = Depends(_service),
) -> ProjectMetricTargetRead:
    target = await service.update_target(project_id, metric_id, target_id, payload)
    return ProjectMetricTargetRead.model_validate(target)


@router.delete("/{project_id}/metrics/{metric_id}/targets/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_target(
    project_id: int,
    metric_id: int,
    target_id: int,
    service: ProjectContextService = Depends(_service),
) -> Response:
    await service.delete_target(project_id, metric_id, target_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{project_id}/metrics/{metric_id}/source-match-jobs",
    response_model=KpiSourceMatchJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_kpi_source_match_job(
    project_id: int,
    metric_id: int,
    payload: KpiSourceMatchJobCreate,
    service: ProjectContextService = Depends(_service),
) -> KpiSourceMatchJobRead:
    """Enqueue a background job to find a candidate data source for a KPI."""
    metric = await service.get_metric(project_id, metric_id)
    service._check_version(metric.version, payload.expected_version)
    job_id = await enqueue_match_kpi_data_source(
        tenant_id=service.context.tenant_id,
        project_id=project_id,
        metric_id=metric_id,
        requested_by_user_id=service.context.user_id,
    )
    return KpiSourceMatchJobRead(
        ok=bool(job_id),
        job_id=job_id,
        message="Match job queued." if job_id else "Failed to queue match job.",
    )


# ── Risks ─────────────────────────────────────────────────────────────────


@router.get("/{project_id}/risks", response_model=list[ProjectRiskRead])
async def list_risks(
    project_id: int,
    service: ProjectContextService = Depends(_service),
) -> list[ProjectRiskRead]:
    risks = await service.list_risks(project_id)
    return [ProjectRiskRead.model_validate(r) for r in risks]


@router.post("/{project_id}/risks", response_model=ProjectRiskRead, status_code=status.HTTP_201_CREATED)
async def create_risk(
    project_id: int,
    payload: ProjectRiskCreate,
    service: ProjectContextService = Depends(_service),
) -> ProjectRiskRead:
    risk = await service.create_risk(project_id, payload)
    return ProjectRiskRead.model_validate(risk)


@router.patch("/{project_id}/risks/{risk_id}", response_model=ProjectRiskRead)
async def update_risk(
    project_id: int,
    risk_id: int,
    payload: ProjectRiskUpdate,
    service: ProjectContextService = Depends(_service),
) -> ProjectRiskRead:
    risk = await service.update_risk(project_id, risk_id, payload)
    return ProjectRiskRead.model_validate(risk)


@router.delete("/{project_id}/risks/{risk_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_risk(
    project_id: int,
    risk_id: int,
    service: ProjectContextService = Depends(_service),
) -> Response:
    await service.delete_risk(project_id, risk_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/{project_id}/risks/reorder")
async def reorder_risks(
    project_id: int,
    payload: ReorderRequest,
    service: ProjectContextService = Depends(_service),
) -> dict:
    await service.reorder_risks(project_id, payload)
    return {"ok": True}


# ── Audit ─────────────────────────────────────────────────────────────────


@router.get("/{project_id}/context/audit", response_model=ProjectContextAuditList)
async def list_context_audit(
    project_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    service: ProjectContextService = Depends(_service),
) -> ProjectContextAuditList:
    """Return append-only audit history for project context changes."""
    items, total = await service.list_audit(project_id, limit=limit, offset=offset)
    return ProjectContextAuditList(
        items=[ProjectContextAuditEventRead.model_validate(i) for i in items],
        total=total,
    )
