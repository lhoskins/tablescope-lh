"""Generate a full dashboard with widgets from a prompt and save it."""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.dashboard import Dashboard
from app.models.file_source_meta import FileSourceMeta
from app.models.saved_query import SavedQuery
from app.services.operational_insight_dashboards import (
    get_or_create_custom_group,
    operational_insight_config,
)

from .ai_proxy_schemas import (
    AIGenerateAndSaveDashboardRequest,
)
from .ai_proxy_shared import (
    _check_project_access,
    _detect_datasource,
    _forward_to_ai,
    _kg_context,
    _relationship_hints,
    _shorten_ai_name,
)
from .ai_proxy_widget_helpers import (
    _NARRATIVE_TYPES,
    _build_join_metadata,
    _correct_widget_chart,
    _derive_dashboard_title,
    _judge_widget,
    _map_widget_visual,
    _norm_col,
    _pack_grid,
)

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/actions/generate-and-save-dashboard")
async def ai_generate_and_save_dashboard(
    req: AIGenerateAndSaveDashboardRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Generate a full dashboard with widgets and save everything.

    Full action flow:
    1. Forward to AI server → LLM proposes dashboard (title, widgets with SQL)
    2. Tablescope validates each widget's SQL
    3. For each widget query, create a SavedQuery
    4. Create Dashboard with widget config referencing queries
    5. Audit trail
    """
    project = await _check_project_access(session, context, req.project_id)

    # Resolve allowed tables from project datasources
    ds_stmt = select(FileSourceMeta).where(
        FileSourceMeta.project_id == req.project_id,
        FileSourceMeta.tenant_id == context.tenant_id,
        FileSourceMeta.archived.is_(False),
    )
    sources = list((await session.execute(ds_stmt)).scalars())
    allowed_tables = [ds.view_name for ds in sources]

    # Step 1 — Plan: ask the AI server for an insight-first dashboard plan.
    kg_context = await _kg_context(
        session, context, req.project_id, surface="dashboard_generation",
        question=req.prompt,
    )
    payload = {
        "tenant_id": context.tenant_id,
        "user_id": context.user_id,
        "project_id": req.project_id,
        "prompt": req.prompt or "",
        "allowed_tables": allowed_tables,
        # Knowledge Graph context steers the plan toward validated risks, gaps,
        # measured/recommended KPIs, and governing documents.
        "knowledge_graph_context": kg_context,
        # Evidence-backed join candidates (e.g. two monthly tables sharing a
        # "month" column) -- lets the planner combine measures that live in
        # separate sources instead of being restricted to one table per widget.
        "relationship_hints": _relationship_hints(sources),
    }
    ai_result = await _forward_to_ai("/ai/dashboard/suggest", payload)
    suggestions = ai_result.get("suggestions", [])

    if not suggestions:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="AI could not generate dashboard suggestions",
        )

    suggestion = suggestions[0]
    if req.name:
        dashboard_title = req.name
    elif suggestion.get("title"):
        dashboard_title = str(suggestion["title"])
    elif req.prompt:
        dashboard_title = _shorten_ai_name(req.prompt)
    else:
        dashboard_title = _derive_dashboard_title(
            project.name, suggestion.get("widgets", [])
        )

    widget_defs = list(suggestion.get("widgets", []))
    # Highest-priority widgets first (executive reading path top-left → bottom-right).
    widget_defs.sort(key=lambda w: float(w.get("priority_score") or 0), reverse=True)

    # Step 2 — Judge: execute each widget's SQL and keep only the strong ones.
    from app.routes.query import (
        _auto_cast_aggregates,
        _resolve_vdb_database,
        _run_sql,
    )
    from app.services.tenant_teiid_resolver import TenantTeiidResolver

    judge_available = True
    teiid_host: str | None = None
    teiid_port: int | None = None
    vdb_database: str | None = None
    try:
        vdb_database = await _resolve_vdb_database(
            session=session, context=context, project_id=req.project_id
        )
        endpoint = await TenantTeiidResolver(session).resolve_for_org(context.tenant_id)
        teiid_host, teiid_port = endpoint.pg_host, endpoint.pg_port
    except Exception as exc:
        # No live VDB (data not materialised yet, or Teiid unavailable): skip the
        # execution-based judge rather than blocking dashboard creation.
        judge_available = False
        logger.warning("Dashboard judge skipped (no VDB): %s", exc)

    kept_defs: list[dict[str, Any]] = []
    dropped_widgets: list[dict[str, str]] = []
    # Widgets kept despite a failed/empty validation run, so the dashboard still
    # saves; they render with an inline "needs attention" state the user can fix.
    flagged_widgets: list[dict[str, str]] = []
    repair_count = 0

    for w in widget_defs:
        title = str(w.get("title", "untitled"))
        wtype = str(w.get("type", "bar")).lower()
        widget_sql = (w.get("sql", "") or "").strip().rstrip(";")

        # Narrative / no-SQL findings cannot be rendered as a dashboard chart.
        if not widget_sql or wtype in _NARRATIVE_TYPES:
            dropped_widgets.append(
                {"title": title, "reason": "narrative finding (no chart)"}
            )
            continue

        validation: dict[str, Any] = {
            "execution_status": "skipped",
            "row_count": 0,
            "columns_returned": [],
            "non_null_metric_count": 0,
            "chart_type_original": wtype,
            "chart_type_final": wtype,
            "sql_original": widget_sql,
            "sql_final": widget_sql,
            "warnings": [],
            "drop_reason": "",
        }

        if judge_available and vdb_database:
            try:
                result = await _run_sql(
                    database=vdb_database,
                    sql=_auto_cast_aggregates(widget_sql),
                    teiid_host=teiid_host,
                    teiid_port=teiid_port,
                )
            except Exception as exc:
                # A failed validation run must not silently delete a widget the
                # user previewed and chose to save. Keep it, flag it, and let the
                # dashboard render an inline error the user can repair.
                logger.warning(
                    "AI dashboard widget flagged (kept) | title=%s reason=%s sql=%s",
                    title, "query failed to execute", widget_sql,
                )
                logger.debug("Widget %r SQL error: %s", title, exc)
                validation.update(
                    {
                        "execution_status": "error",
                        "warnings": ["query failed to execute"],
                        "error": str(exc)[:500],
                    }
                )
                flagged_widgets.append(
                    {"title": title, "reason": "query failed to execute"}
                )
                w["_validation"] = validation
                kept_defs.append(w)
                continue
            cols = result.get("columns", [])
            rows = result.get("rows", [])
            keep, reason = _judge_widget(w, cols, rows)
            if not keep:
                # Weak/empty result: keep but flag rather than dropping, so the
                # previewed dashboard is still created.
                logger.info(
                    "AI dashboard widget flagged (kept) | title=%s reason=%s "
                    "row_count=%d columns=%s",
                    title, reason, len(rows), cols,
                )
                validation.update(
                    {
                        "execution_status": "weak",
                        "row_count": len(rows),
                        "columns_returned": cols,
                        "warnings": [reason],
                    }
                )
                flagged_widgets.append({"title": title, "reason": reason})
                w["_validation"] = validation
                kept_defs.append(w)
                continue
            _correct_widget_chart(w, cols, rows)
            final_type = str(w.get("type", wtype)).lower()
            if final_type != wtype:
                repair_count += 1
            vcol = w.get("value_column") or w.get("y_column") or ""
            non_null = 0
            if vcol:
                col_map = {_norm_col(c): c for c in cols}
                actual = col_map.get(_norm_col(vcol))
                if actual:
                    non_null = sum(1 for r in rows if r.get(actual) is not None)
            validation.update(
                {
                    "execution_status": "success",
                    "row_count": len(rows),
                    "columns_returned": cols,
                    "non_null_metric_count": non_null,
                    "chart_type_final": final_type,
                }
            )

        w["_validation"] = validation
        kept_defs.append(w)

    # Minimum-save rule: a dashboard needs at least one chartable widget. Widgets
    # whose validation query fails or returns weak data are kept (and flagged),
    # so the only widgets that count as unsavable are narrative/no-SQL findings.
    if len(kept_defs) < 1:
        detail = (
            "This suggestion has no chartable widgets to build a dashboard."
        )
        if dropped_widgets:
            detail += " Skipped: " + "; ".join(
                f"{d['title']} ({d['reason']})" for d in dropped_widgets[:6]
            )
        detail += (
            " Try a more specific request, or add data sources that support the "
            "metrics you want to see."
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail
        )

    # Step 3 — Build: for each surviving widget, reuse or create a SavedQuery.
    widgets_config: list[dict[str, Any]] = []
    created_queries: list[int] = []
    reused_queries: list[int] = []

    existing_queries_result = await session.scalars(
        select(SavedQuery).where(SavedQuery.project_id == project.id)
    )
    existing_queries = list(existing_queries_result)

    def _normalize_sql(sql: str) -> str:
        """Normalize SQL for comparison — collapse whitespace and lowercase."""
        return re.sub(r"\s+", " ", sql.strip().rstrip(";").lower())

    sql_to_query: dict[str, SavedQuery] = {}
    for eq in existing_queries:
        if eq.sql_text:
            sql_to_query[_normalize_sql(eq.sql_text)] = eq

    existing_with_sql = [eq for eq in existing_queries if eq.sql_text]

    async def _find_matching_query(widget_sql: str, widget_title: str) -> SavedQuery | None:
        """Use the dedicated /ai/query/match endpoint to find an equivalent query.

        Uses /ai/query/match (NOT the generic /ai/ask): the comparison is a
        purpose-built equivalence check that returns a structured match_id.
        """
        if not existing_with_sql:
            return None
        try:
            match_response = await _forward_to_ai("/ai/query/match", {
                "tenant_id": context.tenant_id,
                "user_id": context.user_id,
                "project_id": req.project_id,
                "candidate_title": widget_title,
                "candidate_sql": widget_sql,
                "existing_queries": [
                    {"id": eq.id, "name": eq.name, "sql": eq.sql_text}
                    for eq in existing_with_sql
                ],
            })
            match_id = match_response.get("match_id")
            if match_id is not None:
                for eq in existing_queries:
                    if eq.id == match_id:
                        return eq
        except Exception:
            logger.warning("AI query matching failed, will create new query")
        return None

    for idx, w in enumerate(kept_defs):
        widget_sql = (w.get("sql", "") or "").strip().rstrip(";")
        widget_title = str(w.get("title", f"Widget {idx + 1}"))
        widget_type = str(w.get("type", "bar"))
        aggregation = (w.get("aggregation") or "count").lower()
        x_col = w.get("label_column") or w.get("x_column") or ""
        y_col = w.get("value_column") or w.get("y_column") or ""
        y2_col = w.get("value_column_2") or ""

        # Tier 1: exact normalized SQL match.
        norm_sql = _normalize_sql(widget_sql)
        existing = sql_to_query.get(norm_sql)
        # Tier 2: AI semantic equivalence match.
        if not existing:
            existing = await _find_matching_query(widget_sql, widget_title)
        # Tier 3: name-based match.
        if not existing:
            candidate_name = f"AI - {widget_title}".lower().strip()
            for eq in existing_queries:
                if eq.name and eq.name.lower().strip() == candidate_name:
                    existing = eq
                    break

        if existing:
            reused_queries.append(existing.id)
            data_source: dict[str, Any] = {"kind": "query", "queryId": existing.id}
        else:
            left_ds = _detect_datasource(widget_sql, allowed_tables)
            query = SavedQuery(
                project_id=project.id,
                owner_id=context.user_id,
                name=f"AI - {widget_title}",
                description=str(w.get("business_question") or ""),
                sql_text=widget_sql,
                left_datasource=left_ds,
                ai_generated=True,
            )
            session.add(query)
            await session.flush()
            created_queries.append(query.id)
            data_source = {"kind": "query", "queryId": query.id}
            sql_to_query[norm_sql] = query
            existing_queries.append(query)

        base_type, subtype = _map_widget_visual(widget_type)
        default_w = {"kpi": 3, "table": 12, "pie": 5}.get(base_type, 6)
        default_h = {"kpi": 2, "table": 5}.get(base_type, 4)
        grid_w = int(w.get("gridW") or w.get("grid_w") or default_w)
        grid_h = int(w.get("gridH") or w.get("grid_h") or default_h)

        widget_conf: dict[str, Any] = {
            "id": f"ai_widget_{idx}",
            "title": widget_title,
            "type": base_type,
            "chartSubtype": subtype,
            # Preserve the planner's richer chart type so the UI can render it
            # natively later even though it maps to a base type for now.
            "aiChartType": widget_type,
            "dataSource": data_source,
            "xColumn": x_col,
            "yColumn": y_col,
            "aggregation": (
                aggregation
                if aggregation in ("sum", "avg", "count", "min", "max")
                else "count"
            ),
            "sortBy": "x_asc",
            "filters": [],
            "position": idx,
            "gridW": grid_w,
            "gridH": grid_h,
        }
        if y2_col:
            widget_conf["y2Column"] = y2_col

        # Per-widget execution validation metadata captured by the judge.
        validation_meta = w.get("_validation")
        if isinstance(validation_meta, dict):
            widget_conf["validation"] = validation_meta

        # Join-quality metadata when the widget uses a multi-table join.
        join_meta = _build_join_metadata(w)
        if join_meta is not None:
            widget_conf["joinMetadata"] = join_meta

        # Carry reference lines (thresholds/SLAs) the planner grounded in docs.
        ref_lines: list[dict[str, Any]] = []
        for rl in (w.get("reference_lines") or []):
            value = rl.get("value") if isinstance(rl, dict) else None
            if value is None:
                continue
            try:
                ref_lines.append(
                    {
                        "axis": "y",
                        "value": float(value),
                        "label": (rl.get("label") or rl.get("source_document") or ""),
                    }
                )
            except (TypeError, ValueError):
                continue
        if ref_lines:
            widget_conf["visualizationOptions"] = {"referenceLines": ref_lines}

        widgets_config.append(widget_conf)

    # Lay widgets out on the 12-column grid in priority order.
    _pack_grid(widgets_config)

    # Dashboard-level validation summary (doc §11). A simple quality score:
    # fraction of generated widgets that survived validation.
    approved_count = len(widgets_config)
    dropped_count = len(dropped_widgets)
    total_generated = approved_count + dropped_count
    quality_score = (
        round(approved_count / total_generated, 2) if total_generated else 0.0
    )
    validation_summary = (
        f"approved={approved_count} dropped={dropped_count} "
        f"repaired={repair_count} quality={quality_score}"
    )
    rejected_insights = list(suggestion.get("rejected_insights", []))

    logger.info(
        "AI dashboard validation | dashboard=%s approved=%d dropped=%d "
        "repaired=%d quality=%s",
        dashboard_title, approved_count, dropped_count, repair_count,
        quality_score,
    )

    # Step 4: Create the Dashboard in the canonical Operational Insight
    # framework. AI-generated dashboards must never fall back to the legacy
    # dashboard chrome or create another Custom dashboards group.
    group = await get_or_create_custom_group(
        session, tenant_id=context.tenant_id, project_id=project.id
    )
    dashboard = Dashboard(
        project_id=project.id,
        owner_id=context.user_id,
        tenant_id=context.tenant_id,
        name=dashboard_title,
        description=(
            req.description
            or suggestion.get("executive_summary")
            or req.prompt
            or ""
        ),
        # AI-generated (operational_insight) dashboards go live immediately --
        # the ITSM-style header they render with has no draft/publish concept.
        status="published",
        config=operational_insight_config(
            {
                "widgets": widgets_config,
                "globalFilters": [],
                "ai_generated": True,
                "generation_pipeline_version": "insight_first_v1",
                "business_domain": suggestion.get("business_domain", ""),
                "intended_audience": suggestion.get("intended_audience", ""),
                "executive_summary": suggestion.get("executive_summary", ""),
                "dashboard_quality_score": quality_score,
                "approved_widget_count": approved_count,
                "dropped_widget_count": dropped_count,
                "flagged_widget_count": len(flagged_widgets),
                "repair_count": repair_count,
                "rejected_insights": rejected_insights,
                "validation_summary": validation_summary,
            },
            group=group,
            dashboard_name=dashboard_title,
        ),
    )
    session.add(dashboard)
    await session.commit()
    await session.refresh(dashboard)

    logger.info(
        "AI action: generate_and_save_dashboard | dashboard_id=%d widgets=%d "
        "dropped=%d queries_created=%d queries_reused=%d project=%d tenant=%d user=%d",
        dashboard.id, len(widgets_config), len(dropped_widgets),
        len(created_queries), len(reused_queries), project.id,
        context.tenant_id, context.user_id,
    )
    return {
        "action": "generate_and_save_dashboard",
        "status": "saved",
        "dashboard_id": dashboard.id,
        "dashboard_name": dashboard_title,
        "widgets_created": len(widgets_config),
        "widgets_dropped": dropped_widgets,
        "widgets_flagged": flagged_widgets,
        "queries_created": created_queries,
        "queries_reused": reused_queries,
        "model_used": ai_result.get("model_used", ""),
        # KG-50: the active KG version + evidence ids that grounded this
        # dashboard's plan.
        "kgGrounding": kg_context.get("kg_grounding"),
    }
