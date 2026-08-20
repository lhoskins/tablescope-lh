"""Dashboard groups and legacy template binding retirement."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.dashboard import Dashboard
from app.models.dashboard_template import DashboardGroup
from app.routes.dashboards_crud import _require_project_access
from app.services.operational_insight_dashboards import (
    CUSTOM_GROUP_SLUG,
    get_or_create_custom_group,
)

router = APIRouter(prefix="/projects/{project_id}", tags=["dashboard-templates"])


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    icon: str = "activity"
    template_id: str | None = None
    collapsed_default: bool = True


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    icon: str | None = None
    position: int | None = None
    collapsed_default: bool | None = None


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "dashboard-group"


def _group_out(group: DashboardGroup, dashboard_ids: list[int] | None = None) -> dict[str, Any]:
    return {
        "id": group.id,
        "name": group.name,
        "slug": group.slug,
        "icon": group.icon,
        "templateId": group.template_id,
        "position": group.position,
        "collapsedDefault": group.collapsed_default,
        "dashboardIds": dashboard_ids or [],
    }


async def _get_group(
    project_id: int,
    group_id: int,
    session: AsyncSession,
    context: RequestContext,
) -> DashboardGroup:
    group = await session.get(DashboardGroup, group_id)
    if group is None or group.project_id != project_id or group.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Dashboard group not found")
    return group


@router.get("/dashboard-groups")
async def list_dashboard_groups(
    project_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[dict[str, Any]]:
    await _require_project_access(project_id, session, context)
    groups = list(
        await session.scalars(
            select(DashboardGroup)
            .where(
                DashboardGroup.project_id == project_id,
                DashboardGroup.tenant_id == context.tenant_id,
            )
            .order_by(DashboardGroup.position, DashboardGroup.name)
        )
    )
    dashboards = list(
        await session.scalars(
            select(Dashboard).where(
                Dashboard.project_id == project_id,
                Dashboard.tenant_id == context.tenant_id,
            )
        )
    )
    members: dict[int, list[int]] = {group.id: [] for group in groups}
    for dashboard in dashboards:
        group_id = (dashboard.config or {}).get("dashboardGroupId")
        if group_id in members:
            members[group_id].append(dashboard.id)
    return [_group_out(group, members[group.id]) for group in groups]


@router.post("/dashboard-groups", status_code=201)
async def create_dashboard_group(
    project_id: int,
    body: GroupCreate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    await _require_project_access(project_id, session, context)
    base, slug, suffix = _slug(body.name), _slug(body.name), 2
    if slug == CUSTOM_GROUP_SLUG:
        group = await get_or_create_custom_group(
            session,
            tenant_id=context.tenant_id,
            project_id=project_id,
        )
        await session.commit()
        await session.refresh(group)
        return _group_out(group)
    while await session.scalar(
        select(DashboardGroup.id)
        .where(
            DashboardGroup.tenant_id == context.tenant_id,
            DashboardGroup.project_id == project_id,
            DashboardGroup.slug == slug,
        )
    ):
        slug, suffix = f"{base}-{suffix}", suffix + 1
    position = int(
        await session.scalar(
            select(func.count())
            .select_from(DashboardGroup)
            .where(
                DashboardGroup.project_id == project_id,
                DashboardGroup.tenant_id == context.tenant_id,
            )
        )
        or 0
    )
    group = DashboardGroup(
        tenant_id=context.tenant_id,
        project_id=project_id,
        name=body.name.strip(),
        slug=slug,
        icon=body.icon,
        template_id=body.template_id,
        position=position,
        collapsed_default=body.collapsed_default,
    )
    session.add(group)
    await session.commit()
    await session.refresh(group)
    return _group_out(group)


@router.put("/dashboard-groups/{group_id}")
async def update_dashboard_group(
    project_id: int,
    group_id: int,
    body: GroupUpdate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    await _require_project_access(project_id, session, context)
    group = await _get_group(project_id, group_id, session, context)
    for field in ("name", "icon", "position", "collapsed_default"):
        value = getattr(body, field)
        if value is not None:
            setattr(group, field, value.strip() if isinstance(value, str) else value)
    await session.commit()
    await session.refresh(group)
    return _group_out(group)


@router.delete("/dashboard-groups/{group_id}", status_code=204, response_class=Response)
async def delete_dashboard_group(
    project_id: int,
    group_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> Response:
    await _require_project_access(project_id, session, context)
    group = await _get_group(project_id, group_id, session, context)
    dashboards = list(
        await session.scalars(
            select(Dashboard).where(
                Dashboard.project_id == project_id,
                Dashboard.tenant_id == context.tenant_id,
            )
        )
    )
    for dashboard in dashboards:
        config = dict(dashboard.config or {})
        if config.get("dashboardGroupId") == group_id:
            config.pop("dashboardGroupId", None)
            dashboard.config = config
    await session.delete(group)
    await session.commit()
    return Response(status_code=204)


@router.post("/dashboard-groups/{group_id}/dashboards/{dashboard_id}")
async def assign_dashboard_group(
    project_id: int,
    group_id: int,
    dashboard_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, int]:
    await _require_project_access(project_id, session, context)
    group = await _get_group(project_id, group_id, session, context)
    dashboard = await session.get(Dashboard, dashboard_id)
    if (
        dashboard is None
        or dashboard.project_id != project_id
        or dashboard.tenant_id != context.tenant_id
    ):
        raise HTTPException(status_code=404, detail="Dashboard not found")
    config = dict(dashboard.config or {})
    config["dashboardGroupId"] = group.id
    metadata = dict(config.get("dashboardTemplate") or {})
    metadata.update(
        {"groupId": f"group:{group.id}", "groupName": group.name, "groupIcon": group.icon}
    )
    config["dashboardTemplate"] = metadata
    dashboard.config = config
    await session.commit()
    return {"dashboardId": dashboard.id, "groupId": group.id}


@router.post("/dashboard-template-bindings{path:path}")
@router.get("/dashboard-template-bindings{path:path}")
@router.put("/dashboard-template-bindings{path:path}")
async def retired_template_bindings(
    path: str = "",
) -> Any:
    """Legacy template binding endpoints have been retired."""
    raise HTTPException(
        status_code=410,
        detail="Legacy template binding endpoints have been retired. Use the AI dashboard designer.",
    )
