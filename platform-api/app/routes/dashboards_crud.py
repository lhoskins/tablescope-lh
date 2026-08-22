"""Dashboard CRUD routes — scoped to project + tenant.

Standard CRUD (list, create, get, update, delete). Also hosts the shared
project-access guard used by the sibling dashboard route modules.
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.dashboard import Dashboard
from app.models.dashboard_primary_dimension import (
    DashboardPrimaryDimension,
    DashboardPrimaryDimensionAssignment,
)
from app.models.project import Project
from app.routes.ai_proxy_dashboard_designer import _dimension_parameters
from app.services.dashboard_widget import find_or_create_saved_query
from app.services.operational_insight_dashboards import (
    operational_insight_config,
    resolve_dashboard_group,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects/{project_id}/dashboards", tags=["dashboards"])


# ── Schemas ──────────────────────────────────────────────────────────

class DashboardCreate(BaseModel):
    name: str
    description: str | None = None
    config: dict = {}
    status: str = "draft"
    ai_generated: bool = False


class DashboardUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    config: dict | None = None
    status: str | None = None
    ai_generated: bool | None = None


class DashboardRead(BaseModel):
    id: int
    project_id: int
    owner_id: int | None
    tenant_id: int
    name: str
    description: str | None
    status: str
    config: dict
    ai_generated: bool = False
    view_count: int = 0
    created_at: datetime
    updated_at: datetime


class DashboardPrimaryDimensionRead(BaseModel):
    id: int
    label: str
    is_active: bool


# ── Helpers ──────────────────────────────────────────────────────────

async def _require_project_access(
    project_id: int,
    session: AsyncSession,
    context: RequestContext,
) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=403, detail="Not in this tenant")
    return project


# ── Endpoints ────────────────────────────────────────────────────────

@router.post("", response_model=DashboardRead, status_code=201)
async def create_dashboard(
    project_id: int,
    body: DashboardCreate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> DashboardRead:
    project = await _require_project_access(project_id, session, context)
    requested_group_id = body.config.get("dashboardGroupId")
    group = await resolve_dashboard_group(
        session,
        tenant_id=context.tenant_id,
        project_id=project.id,
        requested_group_id=requested_group_id
        if isinstance(requested_group_id, int)
        else None,
    )
    dashboard = Dashboard(
        project_id=project.id,
        owner_id=context.user_id,
        tenant_id=context.tenant_id,
        name=body.name,
        description=body.description,
        status=body.status,
        config=operational_insight_config(
            body.config, group=group, dashboard_name=body.name
        ),
        ai_generated=body.ai_generated,
    )
    session.add(dashboard)
    await session.commit()
    await session.refresh(dashboard)
    return DashboardRead.model_validate(dashboard, from_attributes=True)


@router.get("", response_model=list[DashboardRead])
async def list_dashboards(
    project_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[DashboardRead]:
    await _require_project_access(project_id, session, context)
    rows = await session.scalars(
        select(Dashboard)
        .where(
            Dashboard.project_id == project_id,
            Dashboard.tenant_id == context.tenant_id,
        )
        .order_by(Dashboard.updated_at.desc())
    )
    return [DashboardRead.model_validate(d, from_attributes=True) for d in rows]


@router.get("/{dashboard_id}", response_model=DashboardRead)
async def get_dashboard(
    project_id: int,
    dashboard_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> DashboardRead:
    await _require_project_access(project_id, session, context)
    dashboard = await session.get(Dashboard, dashboard_id)
    if dashboard is None or dashboard.project_id != project_id:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return DashboardRead.model_validate(dashboard, from_attributes=True)


@router.put("/{dashboard_id}", response_model=DashboardRead)
async def update_dashboard(
    project_id: int,
    dashboard_id: int,
    body: DashboardUpdate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> DashboardRead:
    await _require_project_access(project_id, session, context)
    dashboard = await session.get(Dashboard, dashboard_id)
    if dashboard is None or dashboard.project_id != project_id:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    if body.name is not None:
        dashboard.name = body.name
    if body.description is not None:
        dashboard.description = body.description
    if body.config is not None:
        if body.config.get("presentation") != "operational_insight":
            raise HTTPException(
                status_code=422,
                detail="Dashboards must use the operational_insight presentation.",
            )
        dashboard.config = body.config
    if body.status is not None:
        dashboard.status = body.status
    if body.ai_generated is not None:
        dashboard.ai_generated = body.ai_generated
    await session.commit()
    await session.refresh(dashboard)
    return DashboardRead.model_validate(dashboard, from_attributes=True)


@router.get(
    "/{dashboard_id}/primary-dimensions",
    response_model=list[DashboardPrimaryDimensionRead],
)
async def list_dashboard_primary_dimensions(
    project_id: int,
    dashboard_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[DashboardPrimaryDimensionRead]:
    """Full-coverage dimensions assigned to this dashboard.

    Powers the header's switch icon, which the doc requires to appear only
    when more than one full-coverage dimension is assigned -- so the
    frontend fetches this list to decide whether to render it at all.
    """
    await _require_project_access(project_id, session, context)
    dashboard = await session.get(Dashboard, dashboard_id)
    if dashboard is None or dashboard.project_id != project_id or dashboard.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    rows = await session.scalars(
        select(DashboardPrimaryDimensionAssignment)
        .where(
            DashboardPrimaryDimensionAssignment.dashboard_id == dashboard_id,
            DashboardPrimaryDimensionAssignment.tenant_id == context.tenant_id,
            DashboardPrimaryDimensionAssignment.project_id == project_id,
        )
        .order_by(DashboardPrimaryDimensionAssignment.position)
    )
    return [
        DashboardPrimaryDimensionRead(id=a.id, label=a.label, is_active=a.is_active)
        for a in rows
    ]


@router.post(
    "/{dashboard_id}/primary-dimensions/{assignment_id}/activate",
    response_model=DashboardRead,
)
async def activate_dashboard_primary_dimension(
    project_id: int,
    dashboard_id: int,
    assignment_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> DashboardRead:
    """Switch a dashboard's active primary dimension and reload its values.

    Reuses the same distinct-values SavedQuery and ``valueSource: "query"``
    template-parameter shape the AI designer's apply step already produces
    (``find_or_create_saved_query`` is keyed by normalized SQL, so this finds
    the existing query rather than duplicating it).
    """
    await _require_project_access(project_id, session, context)
    dashboard = await session.get(Dashboard, dashboard_id)
    if dashboard is None or dashboard.project_id != project_id or dashboard.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    assignments = list(
        await session.scalars(
            select(DashboardPrimaryDimensionAssignment).where(
                DashboardPrimaryDimensionAssignment.dashboard_id == dashboard_id,
                DashboardPrimaryDimensionAssignment.tenant_id == context.tenant_id,
                DashboardPrimaryDimensionAssignment.project_id == project_id,
            )
        )
    )
    target = next((a for a in assignments if a.id == assignment_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Dimension assignment not found")

    dimension = await session.get(DashboardPrimaryDimension, target.dimension_id)
    if dimension is None or dimension.tenant_id != context.tenant_id or dimension.project_id != project_id:
        raise HTTPException(status_code=404, detail="Dimension not found")

    for assignment in assignments:
        assignment.is_active = assignment.id == target.id

    quoted_field = f'"{dimension.field}"'
    quoted_view = f'"{dimension.source_view}"'
    distinct_query = await find_or_create_saved_query(
        session,
        project_id=project_id,
        title=f"AI - {target.label} values",
        sql=f"SELECT DISTINCT {quoted_field} AS value FROM {quoted_view} ORDER BY 1",
        user_id=context.user_id,
        allowed_tables=[dimension.source_view],
    )

    existing_parameters = ((dashboard.config or {}).get("dashboardTemplate") or {}).get("parameters") or {}
    default_period = str(existing_parameters.get("defaultPeriod") or "30_days")
    parameters = await _dimension_parameters(
        session,
        project_id=project_id,
        dimension_label=target.label,
        default_period=default_period,
        query_id=distinct_query.id,
    )
    next_config = dict(dashboard.config or {})
    metadata = dict(next_config.get("dashboardTemplate") or {})
    metadata["parameters"] = parameters
    next_config["dashboardTemplate"] = metadata
    dashboard.config = next_config

    await session.commit()
    await session.refresh(dashboard)
    return DashboardRead.model_validate(dashboard, from_attributes=True)


@router.delete("/{dashboard_id}", status_code=204, response_class=Response)
async def delete_dashboard(
    project_id: int,
    dashboard_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> Response:
    await _require_project_access(project_id, session, context)
    dashboard = await session.get(Dashboard, dashboard_id)
    if dashboard is None or dashboard.project_id != project_id:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    await session.delete(dashboard)
    await session.commit()
    return Response(status_code=204)
