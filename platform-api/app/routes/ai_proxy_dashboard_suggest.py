"""Dashboard suggestion plans with rendered preview widgets."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.file_source_meta import FileSourceMeta

from .ai_proxy_schemas import (
    AISuggestDashboardsRequest,
)
from .ai_proxy_shared import (
    _check_project_access,
    _forward_to_ai,
    _kg_context,
    _kg_context_chips,
    _relationship_hints,
)
from .ai_proxy_widget_helpers import (
    _derive_dashboard_title,
    _suggestion_save_prompt,
)

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/actions/suggest-dashboards")
async def ai_suggest_dashboards(
    req: AISuggestDashboardsRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
    stop_after_first_valid: bool = False,
) -> dict[str, Any]:
    """Return >= 3 dashboard plan suggestions for a project (insight-first).

    Mirrors the Home "New Dashboard Suggestions" flow on the Dashboard page.
    These are previews only — nothing is saved. The user saves a chosen plan via
    the existing ``/actions/generate-and-save-dashboard`` pipeline, which runs the
    full SQL validation/judge and drops empty widgets.

    ``stop_after_first_valid``: the LLM call above always proposes >= 3
    candidate plans, but ``_render_preview_widgets`` -- executing every
    widget's SQL against Teiid for the SQL-preview shape -- runs once per
    plan. A caller that only ever uses the first plan with valid widgets
    (``review_dashboard_design``, the AI Dashboard Designer's "Analyze
    data" step) does not need previews for the other 1-2, which were pure
    waste on that path: full per-plan SQL execution 2-3x over, contributing
    the bulk of that step's 3-5 minute latency and the intermittent 504s at
    nginx's 300s proxy_read_timeout. Defaults to False so the direct
    ``/actions/suggest-dashboards`` HTTP endpoint (Home's "New Dashboard
    Suggestions", which lets the user browse all of them) is unaffected.
    """
    project = await _check_project_access(session, context, req.project_id)

    # Allowed tables = the project's real datasources (reference docs excluded).
    ds_stmt = select(FileSourceMeta).where(
        FileSourceMeta.project_id == req.project_id,
        FileSourceMeta.tenant_id == context.tenant_id,
        FileSourceMeta.archived.is_(False),
    )
    sources = list((await session.execute(ds_stmt)).scalars())
    allowed_tables = [ds.view_name for ds in sources]
    # Evidence-backed join candidates (e.g. two monthly tables sharing a
    # "month" column) -- lets the planner combine measures that live in
    # separate sources (actuals vs. a forecast table) instead of being
    # restricted to one table per widget with no way to express that.
    relationship_hints = _relationship_hints(sources)

    # Real KPI names from the project graph (never invented).
    from app.models.ai_project_graph import AIProjectGraphNode

    kpi_rows = (
        await session.scalars(
            select(AIProjectGraphNode.name).where(
                AIProjectGraphNode.tenant_id == context.tenant_id,
                AIProjectGraphNode.project_id == req.project_id,
                AIProjectGraphNode.is_active.is_(True),
                AIProjectGraphNode.node_type.in_(("kpi", "metric")),
            )
        )
    ).all()
    kpis = [k for k in kpi_rows if k]

    kg_context = await _kg_context(
        session, context, req.project_id, surface="dashboard_generation",
    )

    desired = max(3, int(req.desired_count or 3))
    payload = {
        "tenant_id": context.tenant_id,
        "user_id": context.user_id,
        "project_id": req.project_id,
        "prompt": req.prompt or "",
        "audience": req.audience or "",
        "desired_count": desired,
        "allowed_tables": allowed_tables,
        "kpis": kpis,
        # Steer each preview toward the graph's risks/gaps/KPIs/governing docs.
        "knowledge_graph_context": kg_context,
        "relationship_hints": relationship_hints,
    }
    ai_result = await _forward_to_ai("/ai/dashboard/suggest-multi", payload)
    raw_suggestions = ai_result.get("suggestions", []) or []

    # Compact, chip-friendly KG summary the FE renders on each preview card.
    kg_chips = _kg_context_chips(kg_context)

    # A runner bound to this project's VDB so each widget's SQL is executed and
    # turned into real, renderable chart series (same as the Home dashboard
    # suggestions). Previews are best-effort: a widget that fails or returns no
    # rows is still returned (status != "valid") so the preview never collapses.
    from app.routes.home_intelligence_suite import _make_runner

    runner = _make_runner(session, context, req.project_id)

    suggestions: list[dict[str, Any]] = []
    for idx, s in enumerate(raw_suggestions):
        if not isinstance(s, dict):
            continue
        # Only surface allowed tables as data sources (defence in depth).
        data_sources = [
            str(d) for d in s.get("data_sources", []) if str(d) in allowed_tables
        ]
        title = str(
            s.get("title")
            or s.get("business_purpose")
            or _derive_dashboard_title(
                project.name, list(s.get("widgets", []))
            )
            or "AI Dashboard"
        )
        description = str(s.get("description", ""))
        business_purpose = str(s.get("business_purpose", ""))
        audience = str(s.get("audience") or req.audience or "")
        kpi_names = [str(k) for k in s.get("kpis", []) if k]
        widgets = await _render_preview_widgets(runner, s.get("widgets", []))
        # savePayload is echoed back verbatim on Save so the save stage persists
        # *this* selected suggestion (its real widget SQL) rather than
        # re-deriving a plan from scratch.
        save_payload = {
            "title": title,
            "description": description,
            "businessPurpose": business_purpose,
            "audience": audience,
            "prompt": _suggestion_save_prompt(
                title, business_purpose, description, widgets, kpi_names
            ),
            "widgets": widgets,
            "kpis": kpi_names,
            "dataSources": data_sources,
        }
        suggestions.append(
            {
                "id": f"suggestion-{idx + 1}",
                "title": title,
                "description": description,
                "businessPurpose": business_purpose,
                "audience": audience,
                "widgets": widgets,
                "kpis": kpi_names,
                "dataSources": data_sources,
                "confidence": float(s.get("confidence") or 0.0),
                "qualityScore": int(s.get("quality_score") or 0),
                "validationSummary": "",
                "knowledgeGraphContext": kg_chips,
                "savePayload": save_payload,
            }
        )

        if stop_after_first_valid and any(
            isinstance(w, dict) and str(w.get("status") or "") == "valid" and str(w.get("sql") or "").strip()
            for w in widgets
        ):
            break

    logger.info(
        "AI action: suggest_dashboards | count=%d project=%d tenant=%d user=%d",
        len(suggestions), req.project_id, context.tenant_id, context.user_id,
    )
    preview_note = (
        ""
        if suggestions
        else (
            "Tablescope could not build full dashboard previews from the current "
            "data. Refine the request or add more data sources, then try again."
        )
    )
    return {
        "action": "suggest_dashboards",
        "suggestions": suggestions,
        "previewNote": preview_note,
        "model_used": ai_result.get("model_used", ""),
    }


async def _render_preview_widgets(
    runner: Any, raw_widgets: list[Any]
) -> list[dict[str, Any]]:
    """Execute each plan widget's SQL and attach real, renderable chart data.

    Mirrors the Home "New Dashboard Suggestions" flow: the AI returns widget SQL
    grounded in the project's real tables, we run it against the project VDB and
    build a ``{label, value}`` chart series the FE renders with the same widget
    renderer the dashboard uses. Best-effort and side-effect free — a widget that
    has no SQL (narrative/risk/gap), fails to execute, or returns no rows is still
    returned with a non-``valid`` status so the preview never collapses to a
    "not enough strong widgets" error.
    """
    from app.services import home_intelligence as hi

    async def render(w: Any) -> dict[str, Any] | None:
        if not isinstance(w, dict):
            return None
        title = str(w.get("title", ""))
        chart_type = str(w.get("chart_type") or w.get("type") or "")
        business_question = str(w.get("business_question", ""))
        sql = (w.get("sql") or "").strip()
        label_col = str(w.get("label_column", ""))
        value_col = str(w.get("value_column", ""))
        widget: dict[str, Any] = {
            "title": title,
            "chartType": chart_type,
            "businessQuestion": business_question,
            "sql": sql,
            "labelColumn": label_col,
            "valueColumn": value_col,
            "chart": None,
            "previewData": {"columns": [], "rows": []},
            "status": "narrative" if not sql else "preview_only",
        }
        if not sql:
            return widget
        result = await hi._safe_query(runner, sql)
        if result and result.get("rows"):
            widget["previewData"] = {
                "columns": list(result.get("columns", [])),
                "rows": list(result.get("rows", []))[:100],
            }
            widget["status"] = "valid"
            chart = hi._build_chart(
                chart_type or "bar", title, result, label_col, value_col
            )
            if chart:
                widget["chart"] = chart
                # chartType above is the LLM's raw, unvalidated guess (e.g.
                # "dual_line"). _build_chart grounds it in the real result
                # shape and, for a two-metric time series, correctly resolves
                # to combo/bar_line -- but only the nested chart dict carried
                # that, so the widget's own chartType field (what the review
                # UI displays) stayed frozen at the pre-grounding guess even
                # after a genuinely different type was rendered.
                widget["chartType"] = str(
                    chart.get("subtype") or chart.get("type") or chart_type or "bar"
                )
        return widget

    rendered = await asyncio.gather(
        *(render(w) for w in raw_widgets if isinstance(w, dict))
    )
    return [w for w in rendered if w]
