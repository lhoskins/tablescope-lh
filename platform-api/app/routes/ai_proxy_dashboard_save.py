"""Persist a previously previewed dashboard suggestion."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db

from .ai_proxy_dashboard_generate import (
    ai_generate_and_save_dashboard,
)
from .ai_proxy_schemas import (
    AIGenerateAndSaveDashboardRequest,
    AISaveDashboardSuggestionRequest,
)
from .ai_proxy_widget_helpers import (
    _suggestion_save_prompt,
)

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/actions/save-dashboard-suggestion")
async def ai_save_dashboard_suggestion(
    req: AISaveDashboardSuggestionRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Persist a previewed dashboard suggestion using strict save validation.

    Preview (``/actions/suggest-dashboards``) never persists and never raises the
    strict "needed 2, got N" error. Saving is a separate stage:

    * When the previewed suggestion carries executable widget SQL (the normal
      path now), persist exactly those widgets — each SQL is saved as a project
      query and referenced from the dashboard config — so the saved dashboard
      matches what the user previewed.
    * Otherwise fall back to the strict generate-and-save pipeline, which
      re-derives a plan from the prompt and drops widgets that fail to execute.
    """
    s = req.suggestion

    # Persist the previewed widgets directly when they carry runnable SQL.
    sql_widgets = [w for w in s.widgets if (w.sql or "").strip()]
    if sql_widgets:
        from app.routes.home_intelligence import (
            SaveDashboardRequest,
            SaveDashboardWidget,
            home_save_dashboard,
        )

        saved = await home_save_dashboard(
            SaveDashboardRequest(
                project_id=req.project_id,
                title=s.title or "AI Dashboard",
                widgets=[
                    SaveDashboardWidget(
                        title=w.title or "Widget",
                        sql=w.sql,
                        chartType=w.chartType or "bar",
                        labelColumn=w.labelColumn or None,
                        valueColumn=w.valueColumn or None,
                    )
                    for w in sql_widgets
                ],
            ),
            session=session,
            context=context,
        )
        dashboard_id = saved.get("dashboard_id")
        saved["action"] = "save_dashboard_suggestion"
        saved["suggestion_id"] = req.suggestionId
        saved["dashboard_name"] = saved.get("name")
        if dashboard_id is not None:
            saved["dashboard_url"] = (
                f"/projects/{req.project_id}/dashboards/{dashboard_id}"
            )
        logger.info(
            "AI action: save_dashboard_suggestion (direct) | dashboard_id=%s "
            "suggestion=%s widgets=%d project=%d tenant=%d user=%d",
            dashboard_id, req.suggestionId, len(sql_widgets), req.project_id,
            context.tenant_id, context.user_id,
        )
        return saved

    prompt = s.prompt or _suggestion_save_prompt(
        s.title,
        s.businessPurpose,
        s.description,
        [w.model_dump() for w in s.widgets],
        list(s.kpis),
    )
    saved = await ai_generate_and_save_dashboard(
        AIGenerateAndSaveDashboardRequest(
            project_id=req.project_id,
            prompt=prompt or None,
            name=s.title or None,
            description=s.description or None,
        ),
        session=session,
        context=context,
    )
    dashboard_id = saved.get("dashboard_id")
    saved["action"] = "save_dashboard_suggestion"
    saved["suggestion_id"] = req.suggestionId
    if dashboard_id is not None:
        saved["dashboard_url"] = (
            f"/projects/{req.project_id}/dashboards/{dashboard_id}"
        )
    logger.info(
        "AI action: save_dashboard_suggestion | dashboard_id=%s suggestion=%s "
        "project=%d tenant=%d user=%d",
        dashboard_id, req.suggestionId, req.project_id,
        context.tenant_id, context.user_id,
    )
    return saved
