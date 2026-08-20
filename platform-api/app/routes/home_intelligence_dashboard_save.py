"""Explicit saves of AI suggestions into dashboards.

Split from ``home_intelligence.py``; siblings: ``home_intelligence_suite.py``,
``home_intelligence_snapshot.py`` and ``home_intelligence_suggestions.py``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.dashboard import Dashboard
from app.models.file_source_meta import FileSourceMeta
from app.models.project import Project
from app.models.saved_query import SavedQuery
from app.routes.home_intelligence_suggestions import _derive_dashboard_title
from app.routes.home_intelligence_suite import _has_project_edit
from app.services import dashboard_widget as dw
from app.services.operational_insight_dashboards import (
    get_or_create_custom_group,
    operational_insight_config,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai", tags=["AI Intelligence"])


# ── Save a suggestion (explicit user action) ─────────────────────────


class SaveDashboardWidget(BaseModel):
    title: str
    sql: str
    chartType: str = "bar"
    explanation: str | None = None
    labelColumn: str | None = None
    valueColumn: str | None = None
    valueColumn2: str | None = None
    visualizationOptions: dict[str, Any] | None = None


class SaveDashboardRequest(BaseModel):
    project_id: int
    title: str
    widgets: list[SaveDashboardWidget]
    summary: str | None = None
    keyFindings: list[str] = []
    recommendedActions: list[str] = []


@router.post("/home/save-dashboard")
async def home_save_dashboard(
    req: SaveDashboardRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Persist an in-memory dashboard suggestion as a real dashboard.

    Each widget's SQL is saved as a project query (reusing an existing one when
    the SQL matches) and referenced from the dashboard's widget config.
    """
    project = await session.get(Project, req.project_id)
    if (
        project is None
        or project.tenant_id != context.tenant_id
        or not await _has_project_edit(session, context, project)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Project not editable"
        )
    if not req.widgets:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Dashboard has no widgets to save",
        )

    ds_result = await session.execute(
        select(FileSourceMeta).where(
            FileSourceMeta.project_id == req.project_id,
            FileSourceMeta.tenant_id == context.tenant_id,
            FileSourceMeta.archived.is_(False),
        )
    )
    allowed_tables = [ds.view_name for ds in ds_result.scalars()]

    existing_by_sql: dict[str, SavedQuery] = {}
    widgets_config: list[dict[str, Any]] = []
    for idx, w in enumerate(req.widgets):
        sql = (w.sql or "").strip().rstrip(";")
        if not sql:
            continue
        query = await dw.find_or_create_saved_query(
            session,
            project_id=project.id,
            title=f"AI - {w.title}",
            sql=sql,
            user_id=context.user_id,
            allowed_tables=allowed_tables,
            existing_by_sql=existing_by_sql,
        )
        widgets_config.append(
            dw.build_widget_config(
                title=w.title,
                query_id=query.id,
                chart_type=w.chartType,
                label_column=w.labelColumn,
                value_column=w.valueColumn,
                value_column_2=w.valueColumn2,
                visualization_options=w.visualizationOptions,
                explanation=w.explanation or "",
                index=idx,
            )
        )

    group = await get_or_create_custom_group(
        session, tenant_id=context.tenant_id, project_id=project.id
    )
    dashboard_name = req.title or _derive_dashboard_title(
        project.name, [w.model_dump() for w in req.widgets]
    )
    dashboard = Dashboard(
        project_id=project.id,
        owner_id=context.user_id,
        tenant_id=context.tenant_id,
        name=dashboard_name,
        description="",
        # AI-generated (operational_insight) dashboards go live immediately --
        # the ITSM-style header they render with has no draft/publish concept.
        status="published",
        config=operational_insight_config(
            {
                "widgets": widgets_config,
                "globalFilters": [],
                "ai_generated": True,
                "summary": req.summary or "",
                "keyFindings": req.keyFindings,
                "recommendedActions": req.recommendedActions,
            },
            group=group,
            dashboard_name=dashboard_name,
        ),
    )
    session.add(dashboard)
    await session.commit()
    await session.refresh(dashboard)
    return {
        "status": "saved",
        "dashboard_id": dashboard.id,
        "name": dashboard.name,
        "project_id": project.id,
        "widgets_created": len(widgets_config),
    }


class SaveCardToDashboardRequest(BaseModel):
    project_id: int
    source_project_id: int | None = None
    dashboard_id: int | None = None
    dashboard_name: str | None = None
    title: str
    sql: str
    chartType: str = "bar"
    labelColumn: str | None = None
    valueColumn: str | None = None
    valueColumn2: str | None = None
    visualizationOptions: dict[str, Any] | None = None


@router.post("/home/save-card-to-dashboard")
async def save_card_to_dashboard(
    req: SaveCardToDashboardRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Save a single insight card's chart to a new or existing dashboard."""
    project = await session.get(Project, req.project_id)
    if (
        project is None
        or project.tenant_id != context.tenant_id
        or not await _has_project_edit(session, context, project)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Project not editable"
        )

    if (
        req.source_project_id is not None
        and req.source_project_id != project.id
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Dashboard project must match the insight's source project",
        )

    sql = (req.sql or "").strip().rstrip(";")
    if not sql:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="SQL is required to save a chart",
        )
    if not req.title or not req.title.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Widget title is required",
        )

    if req.dashboard_id is not None and req.dashboard_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide either dashboard_id or dashboard_name, not both",
        )

    dashboard: Dashboard | None = None
    if req.dashboard_id is not None:
        dashboard = await session.get(Dashboard, req.dashboard_id)
        if dashboard is None or dashboard.tenant_id != context.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Dashboard not found"
            )
        if dashboard.project_id != project.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Dashboard does not belong to the selected project",
            )
        if dashboard.owner_id != context.user_id and not (
            await _has_project_edit(session, context, project)
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not allowed to edit this dashboard",
            )
    elif not req.dashboard_name or not req.dashboard_name.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="New dashboard name is required",
        )

    ds_result = await session.execute(
        select(FileSourceMeta).where(
            FileSourceMeta.project_id == project.id,
            FileSourceMeta.tenant_id == context.tenant_id,
            FileSourceMeta.archived.is_(False),
        )
    )
    allowed_tables = [ds.view_name for ds in ds_result.scalars()]

    query = await dw.find_or_create_saved_query(
        session,
        project_id=project.id,
        title=req.title,
        sql=sql,
        user_id=context.user_id,
        allowed_tables=allowed_tables,
    )

    if dashboard is None:
        assert req.dashboard_name is not None
        group = await get_or_create_custom_group(
            session, tenant_id=context.tenant_id, project_id=project.id
        )
        widget_id = f"ai_widget_0_{int(datetime.now(UTC).timestamp() * 1000) % 100000}"
        widget_config = dw.build_widget_config(
            title=req.title,
            query_id=query.id,
            chart_type=req.chartType,
            label_column=req.labelColumn,
            value_column=req.valueColumn,
            value_column_2=req.valueColumn2,
            visualization_options=req.visualizationOptions,
            widget_id=widget_id,
            index=0,
        )
        dashboard = Dashboard(
            project_id=project.id,
            owner_id=context.user_id,
            tenant_id=context.tenant_id,
            name=req.dashboard_name.strip(),
            description="",
            # AI-generated (operational_insight) dashboards go live immediately --
            # the ITSM-style header they render with has no draft/publish concept.
            status="published",
            config=operational_insight_config(
                {
                    "widgets": [widget_config],
                    "globalFilters": [],
                    "ai_generated": True,
                },
                group=group,
                dashboard_name=req.dashboard_name.strip(),
            ),
        )
        session.add(dashboard)
    else:
        config = dict(dashboard.config or {})
        widgets: list[dict[str, Any]] = list(config.get("widgets") or [])
        position = len(widgets)
        used_ids = {w.get("id") for w in widgets if w.get("id")}
        suffix = 0
        base_id = f"ai_widget_{position}"
        widget_id = base_id
        while widget_id in used_ids:
            suffix += 1
            widget_id = f"{base_id}_{suffix}"
        widget_config = dw.build_widget_config(
            title=req.title,
            query_id=query.id,
            chart_type=req.chartType,
            label_column=req.labelColumn,
            value_column=req.valueColumn,
            value_column_2=req.valueColumn2,
            visualization_options=req.visualizationOptions,
            widget_id=widget_id,
            index=position,
        )
        widgets.append(widget_config)
        config["widgets"] = widgets
        dashboard.config = config

    await session.flush()
    await session.commit()
    await session.refresh(dashboard)
    return {
        "status": "saved",
        "dashboard_id": dashboard.id,
        "name": dashboard.name,
        "project_id": project.id,
        "query_id": query.id,
        "widget_id": widget_config["id"],
    }
