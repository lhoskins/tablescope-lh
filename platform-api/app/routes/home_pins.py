"""Home Pins — frozen insight snapshots and live widget references.

A pin belongs to one user/tenant. Two kinds are supported:

* ``insight_card`` — a frozen snapshot of an AI-generated insight card.
* ``live_widget`` — a reference to a dashboard widget that refreshes safely.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.home_pin import HomePin
from app.models.project import Project, ProjectMember
from app.models.saved_query import SavedQuery
from app.routes.dashboards import _build_widget_sql
from app.routes.query import (
    _auto_cast_aggregates,
    _resolve_vdb_database,
    _run_sql,
    normalize_teiid_timestamps,
)
from app.services.tenant_teiid_resolver import TenantTeiidResolver

router = APIRouter(prefix="/home-pins", tags=["Home Pins"])

_PIN_TYPE_PATTERN = re.compile(r"^(insight_card|live_widget)$")
_PIN_KEY_PATTERN = re.compile(r"^(insight|widget):[\w-]+(:[\w-]+)*$")


class _LayoutInput(BaseModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(ge=1, le=12)
    h: int = Field(ge=1, le=12)


class CreateHomePinRequest(BaseModel):
    pin_type: str
    pin_key: str
    title: str
    project_id: int | None = None
    config: dict[str, Any] = {}
    layout: _LayoutInput | None = None
    frozen_payload: dict[str, Any] | None = None

    @field_validator("pin_type")
    @classmethod
    def _validate_pin_type(cls, v: str) -> str:
        if not _PIN_TYPE_PATTERN.match(v):
            raise ValueError("pin_type must be insight_card or live_widget")
        return v

    @field_validator("pin_key")
    @classmethod
    def _validate_pin_key(cls, v: str) -> str:
        if not v or len(v) > 255 or not _PIN_KEY_PATTERN.match(v):
            raise ValueError("invalid pin_key")
        return v


class HomePinLayoutUpdate(BaseModel):
    id: int
    grid_x: int = Field(..., ge=0)
    grid_y: int = Field(..., ge=0)
    grid_w: int = Field(..., ge=1, le=12)
    grid_h: int = Field(..., ge=1, le=12)
    position: int = Field(..., ge=0)


class LayoutBatchRequest(BaseModel):
    layout: list[HomePinLayoutUpdate]

    @field_validator("layout")
    @classmethod
    def _validate_layout(cls, v: list[HomePinLayoutUpdate]) -> list[HomePinLayoutUpdate]:
        if not v:
            raise ValueError("layout must contain at least one item")
        return v


class HomePinRead(BaseModel):
    id: int
    pin_type: str
    pin_key: str
    title: str
    project_id: int | None = None
    config: dict[str, Any]
    layout: dict[str, Any]
    frozen_payload: dict[str, Any] | None = None
    last_refreshed_at: str | None = None
    refresh_error: str | None = None
    is_pinned: bool
    created_at: str
    updated_at: str


def _to_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _pin_read(pin: HomePin) -> dict[str, Any]:
    return {
        "id": pin.id,
        "pin_type": pin.pin_type,
        "pin_key": pin.pin_key,
        "title": pin.title,
        "project_id": pin.project_id,
        "config": pin.config or {},
        "layout": pin.layout or {},
        "frozen_payload": pin.frozen_payload,
        "last_refreshed_at": _to_iso(pin.last_refreshed_at),
        "refresh_error": pin.refresh_error,
        "is_pinned": pin.is_pinned,
        "created_at": _to_iso(pin.created_at),
        "updated_at": _to_iso(pin.updated_at),
    }


async def _can_access_project(
    session: AsyncSession,
    context: RequestContext,
    project_id: int | None,
) -> Project | None:
    if project_id is None:
        return None
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        return None
    if project.owner_id == context.user_id:
        return project
    if project.is_shared:
        return project
    member = await session.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == context.user_id,
            ProjectMember.is_active.is_(True),
        )
    )
    if member is None:
        return None
    return project


async def _require_project_access(
    session: AsyncSession,
    context: RequestContext,
    project_id: int | None,
) -> Project | None:
    project = await _can_access_project(session, context, project_id)
    if project_id is not None and project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    return project


@router.get("", response_model=list[HomePinRead])
async def list_home_pins(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[dict[str, Any]]:
    """Return the current user's pinned Home content."""
    rows = await session.scalars(
        select(HomePin)
        .where(
            HomePin.tenant_id == context.tenant_id,
            HomePin.user_id == context.user_id,
            HomePin.is_pinned.is_(True),
        )
        .order_by(HomePin.layout["position"].as_string(), HomePin.id)
    )
    return [_pin_read(p) for p in rows.all()]


@router.post("", response_model=HomePinRead, status_code=201)
async def create_home_pin(
    req: CreateHomePinRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """Pin an insight card or live widget to the Home grid."""
    project = await _require_project_access(session, context, req.project_id)

    existing = await session.scalar(
        select(HomePin).where(
            HomePin.tenant_id == context.tenant_id,
            HomePin.user_id == context.user_id,
            HomePin.pin_key == req.pin_key,
        )
    )
    if existing is not None:
        return _pin_read(existing)

    layout = req.layout.model_dump() if req.layout else {}
    pin = HomePin(
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        project_id=project.id if project else None,
        pin_type=req.pin_type,
        pin_key=req.pin_key,
        title=req.title,
        config=req.config,
        layout=layout,
        frozen_payload=req.frozen_payload,
    )
    session.add(pin)
    await session.commit()
    await session.refresh(pin)
    return _pin_read(pin)


@router.delete("/{pin_id}", status_code=204, response_model=None)
async def delete_home_pin(
    pin_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> None:
    """Unpin a Home item."""
    pin = await session.get(HomePin, pin_id)
    if pin is None or pin.tenant_id != context.tenant_id or pin.user_id != context.user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pin not found")
    await session.delete(pin)
    await session.commit()


@router.patch("/layout", response_model=list[HomePinRead])
async def update_home_pin_layout(
    req: LayoutBatchRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[dict[str, Any]]:
    """Batch update Home pin grid coordinates."""
    ids = {item.id for item in req.layout}
    rows = (
        await session.scalars(
            select(HomePin).where(
                HomePin.id.in_(ids),
                HomePin.tenant_id == context.tenant_id,
                HomePin.user_id == context.user_id,
            )
        )
    ).all()
    found = {p.id: p for p in rows}
    if set(found.keys()) != ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="One or more pins not accessible",
        )

    for item in req.layout:
        pin = found[item.id]
        pin.layout = {
            "x": item.grid_x,
            "y": item.grid_y,
            "w": item.grid_w,
            "h": item.grid_h,
            "position": item.position,
        }

    await session.commit()
    for p in found.values():
        await session.refresh(p)
    return [_pin_read(p) for p in found.values()]


async def _refresh_widget(session: AsyncSession, context: RequestContext, pin: HomePin) -> None:
    """Re-run the underlying query for a live widget pin and cache the result."""
    pin.last_refreshed_at = datetime.now(UTC)
    pin.refresh_error = None

    config = pin.config or {}
    widget = config.get("widget") or {}
    data_source = widget.get("dataSource") or {}
    project_id = pin.project_id
    if not project_id:
        pin.refresh_error = "Widget pin has no project"
        return

    project = await _can_access_project(session, context, project_id)
    if project is None:
        pin.refresh_error = "Project not accessible"
        return

    try:
        if data_source.get("kind") == "query":
            query_id = data_source.get("queryId")
            if not query_id:
                pin.refresh_error = "Missing queryId"
                return
            saved = await session.get(SavedQuery, query_id)
            if saved is None or saved.project_id != project_id:
                pin.refresh_error = "Saved query not found"
                return
            sql = normalize_teiid_timestamps(saved.sql_text or "")
            sql = _auto_cast_aggregates(sql).rstrip().rstrip(";")
        elif data_source.get("kind") == "datasource":
            view_name = data_source.get("viewName")
            if not view_name:
                pin.refresh_error = "Missing viewName"
                return
            # Build a request-shaped dict for the existing widget SQL builder.
            body: dict[str, Any] = {
                "view_name": view_name,
                "x_column": widget.get("xColumn") or "",
                "y_column": widget.get("yColumn") or "",
                "aggregation": widget.get("aggregation") or "sum",
                "date_granularity": widget.get("dateGranularity"),
                "group_by_column": widget.get("groupByColumn"),
                "sort_by": widget.get("sortBy") or "x_asc",
                "limit": widget.get("limit") or 500,
                "filters": widget.get("filters") or [],
                "global_filters": [],
            }
            sql = _build_widget_sql(body)  # type: ignore[arg-type]
        else:
            pin.refresh_error = f"Unsupported data source kind: {data_source.get('kind')}"
            return

        database = await _resolve_vdb_database(
            session=session,
            context=context,
            project_id=project_id,
        )
        endpoint = await TenantTeiidResolver(session).resolve_for_org(context.tenant_id)
        result = await _run_sql(
            database=database,
            sql=sql,
            teiid_host=endpoint.pg_host,
            teiid_port=endpoint.pg_port,
        )
        cached = config.get("cachedData") or {}
        cached["columns"] = result["columns"]
        cached["rows"] = result["rows"]
        config["cachedData"] = cached
        pin.config = config
    except Exception as exc:
        pin.refresh_error = str(exc)[:1024]


@router.post("/{pin_id}/refresh", response_model=HomePinRead)
async def refresh_home_pin(
    pin_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """Refresh a single live widget pin."""
    pin = await session.get(HomePin, pin_id)
    if pin is None or pin.tenant_id != context.tenant_id or pin.user_id != context.user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pin not found")

    if pin.pin_type == "live_widget":
        await _refresh_widget(session, context, pin)
    else:
        pin.last_refreshed_at = datetime.now(UTC)

    await session.commit()
    await session.refresh(pin)
    return _pin_read(pin)


@router.post("/refresh")
async def refresh_all_home_pins(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """Refresh all live widget pins for the current user."""
    rows = await session.scalars(
        select(HomePin).where(
            HomePin.tenant_id == context.tenant_id,
            HomePin.user_id == context.user_id,
            HomePin.is_pinned.is_(True),
            HomePin.pin_type == "live_widget",
        )
    )
    pins = rows.all()
    refreshed = 0
    errors = 0
    for pin in pins:
        await _refresh_widget(session, context, pin)
        if pin.refresh_error:
            errors += 1
        else:
            refreshed += 1
    await session.commit()
    return {"refreshed": refreshed, "errors": errors, "total": len(pins)}
