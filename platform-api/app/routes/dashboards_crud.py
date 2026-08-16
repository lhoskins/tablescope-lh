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
from app.models.project import Project
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
        dashboard.config = body.config
    if body.status is not None:
        dashboard.status = body.status
    if body.ai_generated is not None:
        dashboard.ai_generated = body.ai_generated
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
