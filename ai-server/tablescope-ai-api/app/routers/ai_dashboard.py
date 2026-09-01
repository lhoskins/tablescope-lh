"""Dashboard suggestion endpoints (single spec and multi-dashboard plan)."""

import logging
import uuid

from fastapi import APIRouter, HTTPException, status

from app.core.activity import update_activity
from app.core.config import settings
from app.core.security import verify_signature
from app.models.schemas import (
    DashboardPlanSuggestion,
    DashboardPlanWidget,
    SuggestDashboardRequest,
    SuggestDashboardResponse,
    SuggestDashboardsMultiRequest,
    SuggestDashboardsMultiResponse,
)
from app.services import context_builder, llm_client
from app.services.context_builder import ContextBuildError
from app.services.kg_context import format_knowledge_graph_context
from app.services.prompt_loader import load_prompt_reference
from app.services.sql_validator import SQLValidationError, validate_sql

from .ai_plan_prompt import _build_relationship_hint_lines, _fit_plan_prompt
from .ai_plan_sql import _ensure_group_by
from .ai_shared import (
    _TEIID_JOIN_EXCEPTION_RULE,
    _TEIID_RULES_COMMON,
    _TEIID_RULES_HEADER,
    _TEIID_SINGLE_TABLE_RULE,
    _TEIID_SQL_RULES,
    _clean_sql,
    _parse_json_response,
)

logger = logging.getLogger(__name__)
router = APIRouter()


_DASHBOARD_INSIGHT_SYSTEM_PROMPT = (
    "You are Tablescope AI acting as a senior business analyst, KPI strategist, "
    "and dashboard designer working inside ONE authorized Tablescope project. "
    "Your job is NOT to create generic charts from whatever tables exist. First "
    "reason about what a well-run company in this domain should monitor, where "
    "risk or opportunity lives, and which insights deserve dashboard placement — "
    "THEN choose the single best visualization for each insight and write the "
    "SQL that proves it.\n"
    "Use ONLY the authorized project context provided in the request (tables, "
    "columns, saved queries, documents, KPI references, reference-library "
    "standards, and relationships). Never reference data outside it. Do not "
    "invent tables, columns, metrics, thresholds, benchmarks, dates, values, or "
    "documents. If the context cannot support a proposed insight, leave it out. "
    "Prefer fewer strong, non-empty, decision-grade widgets over many weak ones."
)


def _dashboard_relationship_floor_line(has_relationship_evidence: bool) -> str:
    """A dashboard-prompt-appropriate counterpart to the plan prompt's floor.

    ai_plan_prompt._build_relationship_floor_line's wording ("the single-table
    relationship analyses described below", "no other section of this prompt
    (documents, knowledge-graph hypotheses, depth guidance)") refers to
    /ai/intelligence/plan's specific "analyses by category" structure, which
    this widget/grid prompt does not have. Reusing it verbatim here dangled a
    reference to a section that does not exist in this prompt -- confusing
    boilerplate a smaller model can misread, at worst degrading unrelated
    single-table output. With no evidence there is nothing to floor, so this
    returns "" rather than injecting text that fits a different prompt shape.
    """
    if not has_relationship_evidence:
        return ""
    return (
        "The RELATIONSHIP EVIDENCE list above is non-empty: include at least "
        "one widget built as an EXPLICIT JOIN across those verified keys (see "
        "the join exception above) whenever the data supports a genuine "
        "cross-table insight -- do not restrict every widget to a single "
        "table just because most of them are.\n"
    )


@router.post("/dashboard/suggest", response_model=SuggestDashboardResponse)
async def suggest_dashboard(req: SuggestDashboardRequest) -> SuggestDashboardResponse:
    """Suggest dashboard widgets based on project data (insight-first).

    Reasons like a senior analyst over the project's real schema, documents, KPI
    references, and reference library, then emits chart-ready widget specs with
    validation expectations and priority/confidence scores. The platform-api
    judge stage executes each widget's SQL and drops empty/weak ones before save.
    """
    request_id = str(uuid.uuid4())
    verify_signature(req.model_dump(exclude={"signature"}, exclude_unset=True), req.signature)

    try:
        ctx = await context_builder.build_context(
            tenant_id=req.tenant_id,
            user_id=req.user_id,
            project_id=req.project_id,
            scope="project",
            question="",
            feature="suggest_dashboard",
        )
    except ContextBuildError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: {e.reason}",
        )

    context_text = context_builder.context_to_prompt_text(ctx)

    # Determine allowed tables
    allowed_tables = req.allowed_tables
    if not allowed_tables:
        allowed_tables = [
            ds.get("view_name", ds.get("name", ""))
            for ds in ctx.allowed_context.get("metadata", [])
            if ds.get("view_name") or ds.get("name")
        ]

    user_instruction = ""
    if req.prompt:
        user_instruction = f"\nUser request: {req.prompt}\n"

    chart_catalog = (
        "Supported chart types — pick the SINGLE best one per insight; never "
        "default everything to bar:\n"
        "- kpi / kpi_grid: one or a few executive headline numbers (single-row aggregate).\n"
        "- bar (vertical): compact category comparisons or period buckets.\n"
        "- horizontal_bar: ranked categories with long labels — suppliers, customers, products, regions, top-N.\n"
        "- stacked_bar: category composition over another category or period.\n"
        "- grouped_bar: side-by-side comparison of 2+ metrics across categories.\n"
        "- line: trends over time.\n"
        "- dual_line: two related metrics over the same time axis.\n"
        "- area: cumulative or volume-over-time.\n"
        "- pie / donut: true part-to-whole share with 2-8 slices only.\n"
        "- table / pivot_table: operational detail users can act on.\n"
        "- heatmap: a metric across two categorical dimensions (intensity).\n"
        "- scatter / bubble: relationship/correlation between two (or three) metrics.\n"
        "- treemap: many categories' relative sizes.\n"
        "- waterfall: bridge analysis / variance decomposition / contribution to change.\n"
        "- funnel: stage conversion / drop-off.\n"
        "- gauge / bullet: a metric vs an explicit target, threshold, SLA, or benchmark.\n"
        "- radar: multi-metric comparison of a few items.\n"
        "- sparkline_table: many entities each with an inline trend + current value.\n"
        "- narrative_insight: a document-driven finding better told as prose (no SQL).\n"
    )

    best_practices = load_prompt_reference("dashboard_best_practices.md")
    best_practices_block = (
        f"Dashboard Best Practices (authoritative policy):\n{best_practices}\n\n"
        if best_practices
        else ""
    )

    kg_block = format_knowledge_graph_context(req.knowledge_graph_context)
    kg_prompt_block = f"{kg_block}\n\n" if kg_block else ""

    # With relationship evidence in play, the flat "Do NOT write JOINs" rule
    # would contradict (and, sitting later in the prompt, override) the
    # cross-table exception -- swap in the exception-aware variant, exactly
    # as /ai/intelligence/plan already does. Without evidence this is
    # byte-identical to the original single-table rules.
    relationship_lines = _build_relationship_hint_lines(req.relationship_hints)
    teiid_rules = (
        _TEIID_RULES_HEADER + _TEIID_JOIN_EXCEPTION_RULE + _TEIID_RULES_COMMON
        if relationship_lines
        else _TEIID_SQL_RULES
    )
    relationship_floor = _dashboard_relationship_floor_line(bool(relationship_lines))

    prompt = (
        # best_practices_block first: it is the single largest block (the
        # full dashboard_best_practices.md reference, ~19k chars/~5.5k
        # tokens -- over half of _fit_plan_prompt's entire trim budget) and
        # the LEAST request-specific -- static guidance, identical on every
        # call. _fit_plan_prompt trims from the front, so whatever sits
        # first is sacrificed first. Putting it ahead of context_text means
        # an oversized prompt trims generic policy text before it ever
        # touches the project's actual schema -- previously reversed: the
        # per-project schema (which columns this SPECIFIC dashboard's SQL
        # needs) was first in line to be cut while the same boilerplate
        # every request shares was protected near the tail.
        f"{best_practices_block}"
        f"{context_text}\n\n"
        f"{kg_prompt_block}"
        f"Allowed tables (use ONLY these exact names): {', '.join(allowed_tables)}\n\n"
        "CRITICAL: every widget's SQL must reference ONLY the allowed tables "
        "above. Never invent or assume any other table (e.g. Sales, Product, "
        "Customers).\n\n"
        f"{teiid_rules}\n"
        f"{relationship_lines}"
        f"{relationship_floor}\n"
        "Think like a senior business analyst and KPI strategist. Do NOT start "
        "by making charts. First decide what a well-run company in this domain "
        "should monitor, where the risk or opportunity is, and which insights "
        "deserve dashboard placement. THEN, for each insight, choose the single "
        "chart type that best communicates it and write the SQL that proves it.\n\n"
        "Grounding rules:\n"
        "- Use the project's real tables/columns, saved queries, documents, KPI "
        "references, and reference-library standards shown above as evidence.\n"
        "- Do NOT invent tables, columns, metrics, thresholds, dates, or values. "
        "If the context cannot support an insight, leave it out.\n"
        "- Prefer business impact over chart quantity; prefer fewer strong "
        "widgets over many weak ones.\n"
        "- Use reference-library thresholds/SLAs/benchmarks as target lines ONLY "
        "when the value is explicit in the provided content, and cite the "
        "document in reference_lines[].source_document.\n"
        "- For any time-series chart, GROUP BY a sortable STRING period label "
        "built with FORMATTIMESTAMP — default to month 'yyyy-MM' so a single "
        "year still shows a trend; use 'yyyy' only across 3+ years. NEVER group "
        "by a bare numeric year (it collapses to one point and renders as a "
        "meaningless '2.0K' tile). Put the period first in SELECT, ORDER BY it, "
        "and only build a trend when >= 3 periods exist — otherwise use a KPI or "
        "category comparison. When the data spans 2+ years, prefer a "
        "year-over-year view (month on the axis; year as the series or a "
        "prior-year value_column_2) so this year is shown against last year.\n"
        "- Do NOT create a pie/donut unless it is a true part-to-whole with 2-8 "
        "slices. Do NOT create a KPI unless it is an executive-level number.\n"
        "- Avoid WHERE filters on guessed values; only filter on values proven "
        "by the schema/sample context or explicitly requested by the user.\n"
        "- Do NOT include a widget you expect to return no rows.\n\n"
        f"{chart_catalog}\n"
        "SQL rules: read-only, never SELECT *, give every selected expression a "
        "stable alias, and make label_column / value_column / value_column_2 / "
        "series_column / target_column EXACTLY match aliases in the SELECT list. "
        + (
            "Query a single allowed table per widget, with the documented "
            "join exception above.\n\n"
            if relationship_lines
            else "Query a single allowed table per widget (no JOINs).\n\n"
        ) +
        "Layout: 12-column grid. Put the highest-priority executive KPIs in the "
        "top row, place related charts near each other, give trend/table/heatmap/"
        "waterfall charts more width (gridW 8-12), and create a clear top-left to "
        "bottom-right reading path. Aim for 4-8 strong widgets.\n\n"
        f"{user_instruction}\n"
        "Return ONLY a JSON object:\n"
        "{\n"
        '  "title": "specific, descriptive dashboard name (never generic like AI Dashboard)",\n'
        '  "description": "one-line description",\n'
        '  "business_domain": "",\n'
        '  "intended_audience": "executive|manager|analyst|operational",\n'
        '  "executive_summary": "2-3 sentences on what this dashboard answers",\n'
        '  "widgets": [ {\n'
        '    "type": "<one chart type from the catalog>",\n'
        '    "title": "short widget title",\n'
        '    "subtitle": "",\n'
        '    "business_question": "the executive question this answers",\n'
        '    "sql": "SELECT ... (empty for narrative_insight)",\n'
        '    "label_column": "alias for the category/x axis",\n'
        '    "value_column": "alias for the primary numeric value",\n'
        '    "value_column_2": "alias for a 2nd metric (dual_line/scatter/bubble/target) or empty",\n'
        '    "series_column": "alias that splits series (stacked/grouped) or empty",\n'
        '    "target_column": "alias holding a target/threshold (gauge/bullet) or empty",\n'
        '    "x_column": "alias for x (scatter/bubble) or empty",\n'
        '    "y_column": "alias for y (scatter/bubble) or empty",\n'
        '    "aggregation": "count|sum|avg|min|max",\n'
        '    "reference_lines": [ {"label": "", "value": null, "source_document": ""} ],\n'
        '    "drilldown_fields": [],\n'
        '    "validation_expectations": {\n'
        '      "minimum_rows": 1, "required_columns": [], "non_null_columns": [],\n'
        '      "chart_requires_multiple_rows": false, "empty_result_action": "drop_widget"\n'
        "    },\n"
        '    "priority_score": 0,\n'
        '    "confidence_score": 0.0,\n'
        '    "gridX": 0, "gridY": 0, "gridW": 6, "gridH": 4\n'
        "  } ]\n"
        "}\n\n"
        "OUTPUT FORMAT: respond with this JSON object and nothing else — no "
        "prose, no markdown, no code fences. Begin with { and end with }."
    )

    # Trim the prompt from the front while preserving the output-format
    # instructions at the tail, and reserve real output budget explicitly.
    # A large project (many saved queries/dashboards/scopes/datasources) can
    # otherwise fill vLLM's whole context window with prompt, leaving a
    # reasoning model just enough room to think and none to answer -- a
    # confirmed live failure mode (0 widgets, every time, on a large project).
    #
    # This endpoint's per-widget schema is far richer than suggest-multi's
    # (~20 fields: reference_lines, validation_expectations, grid layout,
    # etc. vs. 6), so even one plan's worth of 4-8 widgets can need more than
    # 2048 tokens -- and this is the endpoint the final "Create dashboard"
    # step actually calls to build the saved dashboard, so a truncated
    # response here silently drops widgets (or leaves one mid-generation,
    # e.g. a JOIN cut off before its ON clause) exactly like the confirmed
    # suggest-multi truncation, just for the saved dashboard instead of the
    # review preview.
    logger.info(
        "dashboard suggest prompt len=%d (pre-fit) tenant=%s project=%s",
        len(prompt), req.tenant_id, req.project_id,
    )
    prompt = _fit_plan_prompt(
        prompt, _DASHBOARD_INSIGHT_SYSTEM_PROMPT, max_tokens=3072
    )
    logger.info(
        "dashboard suggest prompt len=%d (post-fit) tenant=%s project=%s",
        len(prompt), req.tenant_id, req.project_id,
    )
    raw = await llm_client.generate(
        prompt=prompt,
        system_prompt=_DASHBOARD_INSIGHT_SYSTEM_PROMPT,
        model=req.model or settings.sql_model,
        temperature=0.3,
        max_tokens=3072,
        # Larger window so the injected dashboard_best_practices reference fits
        # alongside the project context without truncation.
        num_ctx=24576,
        response_format="json",
        llm_target_url=req.llm_target_url,
    )

    suggestions: list[dict] = []
    parsed = _parse_json_response(raw)
    if isinstance(parsed, dict):
        suggestions = [parsed]
    elif isinstance(parsed, list):
        suggestions = [s for s in parsed if isinstance(s, dict)]
    else:
        logger.warning("Failed to parse dashboard suggestions: %s", raw[:200])

    # Post-process: fix Teiid GROUP BY aliases in each widget's SQL, then drop
    # any widget whose SQL references a table outside the project's allowed set.
    # The LLM occasionally hallucinates generic tables (e.g. "Sales", "Product")
    # that do not belong to this tenant/project; those must never reach the user.
    # Widgets with no SQL (narrative_insight) are kept — they are document-driven.
    for s in suggestions:
        kept_widgets = []
        for w in s.get("widgets", []):
            sql = w.get("sql")
            if sql:
                w["sql"] = _ensure_group_by(_clean_sql(sql))
                try:
                    validate_sql(w["sql"], allowed_tables)
                except SQLValidationError as e:
                    logger.warning(
                        "Dropping suggested widget %r: %s",
                        w.get("title", "untitled"), e.reason,
                    )
                    continue
            kept_widgets.append(w)
        # Highest-priority widgets first so the executive reading path is sound.
        kept_widgets.sort(
            key=lambda w: float(w.get("priority_score") or 0), reverse=True
        )
        s["widgets"] = kept_widgets

    update_activity(req.user_id, req.tenant_id, req.project_id)

    return SuggestDashboardResponse(
        suggestions=suggestions,
        request_id=request_id,
        model_used=req.model or settings.sql_model,
    )


@router.post(
    "/dashboard/suggest-multi", response_model=SuggestDashboardsMultiResponse
)
async def suggest_dashboards_multi(
    req: SuggestDashboardsMultiRequest,
) -> SuggestDashboardsMultiResponse:
    """Suggest several distinct dashboard *plans* (insight-first, lightweight).

    Returns at least ``desired_count`` plans, each grounded in the project's real
    tables, KPI references, and reference-library standards. These are previews:
    the heavy SQL validation/build happens on save via the existing
    generate-and-save-dashboard pipeline.
    """
    request_id = str(uuid.uuid4())
    verify_signature(req.model_dump(exclude={"signature"}, exclude_unset=True), req.signature)

    try:
        ctx = await context_builder.build_context(
            tenant_id=req.tenant_id,
            user_id=req.user_id,
            project_id=req.project_id,
            scope="project",
            question="",
            feature="suggest_dashboard",
        )
    except ContextBuildError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: {e.reason}",
        )

    context_text = context_builder.context_to_prompt_text(ctx)

    allowed_tables = req.allowed_tables
    if not allowed_tables:
        allowed_tables = [
            ds.get("view_name", ds.get("name", ""))
            for ds in ctx.allowed_context.get("metadata", [])
            if ds.get("view_name") or ds.get("name")
        ]

    desired = max(3, int(req.desired_count or 3))
    audience_line = (
        f"Target audience: {req.audience}.\n" if req.audience else ""
    )
    user_instruction = f"\nUser request: {req.prompt}\n" if req.prompt else ""
    kpi_line = (
        f"Known project KPIs (cover the relevant ones): {', '.join(req.kpis)}\n"
        if req.kpis
        else ""
    )

    best_practices = load_prompt_reference("dashboard_best_practices.md")
    best_practices_block = (
        f"Dashboard Best Practices (authoritative policy):\n{best_practices}\n\n"
        if best_practices
        else ""
    )

    kg_block = format_knowledge_graph_context(req.knowledge_graph_context)
    kg_prompt_block = f"{kg_block}\n\n" if kg_block else ""

    # Same exception-aware swap /ai/intelligence/plan and /dashboard/suggest
    # use: without relationship evidence this is byte-identical to the
    # original single-table rule, so plans without a discovered join are
    # unaffected.
    relationship_lines = _build_relationship_hint_lines(req.relationship_hints)
    table_rule = _TEIID_RULES_HEADER + (
        _TEIID_JOIN_EXCEPTION_RULE if relationship_lines else _TEIID_SINGLE_TABLE_RULE
    )
    relationship_floor = _dashboard_relationship_floor_line(bool(relationship_lines))

    prompt = (
        # See suggest_dashboard's identical reordering: best_practices_block
        # is the largest block (~19k chars) and the least request-specific
        # (static, identical every call), so it goes first -- _fit_plan_
        # prompt trims from the front, and the project's actual schema in
        # context_text needs to survive that far more than boilerplate does.
        f"{best_practices_block}"
        f"{context_text}\n\n"
        f"{kg_prompt_block}"
        f"Allowed tables (use ONLY these exact names): {', '.join(allowed_tables)}\n\n"
        f"{audience_line}"
        f"{kpi_line}"
        f"Propose {desired} DISTINCT, non-overlapping dashboard PLANS a senior "
        "analyst would build for this project. Each plan must target a different "
        "business theme, audience, or decision (e.g. executive overview, supplier "
        "quality & risk, on-time delivery & operations). Think first about what "
        "matters; do not just regroup the same charts.\n\n"
        "Grounding rules:\n"
        "- Ground every plan in the project's REAL tables, columns, saved "
        "queries, documents, KPI references, and reference-library standards "
        "shown above.\n"
        "- Do NOT invent tables, columns, metrics, KPIs, or data sources. Only "
        "list data_sources from the allowed tables and kpis from the project's "
        "real KPI references.\n"
        "- Reference Library documents are authoritative guidance, NOT data "
        "sources: never list a reference document as a data source.\n"
        f"{table_rule}"
        "- 3-6 widgets per plan. Each chart/table/KPI widget MUST include a "
        "complete, runnable SQL query grounded in the allowed tables/columns "
        "above so the dashboard can render real data. Use exact table and column "
        "names; aggregate where appropriate; add ORDER BY and a small LIMIT "
        "(<= 12 rows) for ranked/top-N widgets.\n"
        "- For each widget also name the label_column (category/x axis) and "
        "value_column (numeric/y axis) from the SELECT list.\n"
        "- A narrative/risk/gap widget (chart_type 'narrative_insight') has an "
        "empty sql; use these sparingly and prefer real data widgets.\n\n"
        f"{relationship_lines}"
        f"{relationship_floor}\n"
        f"{user_instruction}\n"
        f"Return ONLY a JSON object with at least {desired} suggestions:\n"
        "{\n"
        '  "suggestions": [ {\n'
        '    "title": "specific, descriptive dashboard name (unique, never generic like AI Dashboard)",\n'
        '    "description": "one-line description",\n'
        '    "business_purpose": "the decision/question this dashboard drives",\n'
        '    "audience": "executive|manager|analyst|operational",\n'
        '    "widgets": [ {"title": "", "chart_type": "<chart type>", '
        '"business_question": "", "sql": "SELECT ... (empty for '
        'narrative_insight)", "label_column": "", "value_column": ""} ],\n'
        '    "kpis": ["kpi names this dashboard covers"],\n'
        '    "data_sources": ["allowed table names this dashboard uses"],\n'
        '    "confidence": 0.0,\n'
        '    "quality_score": 0\n'
        "  } ]\n"
        "}\n\n"
        "OUTPUT FORMAT: respond with this JSON object and nothing else — no "
        "prose, no markdown, no code fences. Begin with { and end with }."
    )

    # See suggest_dashboard's identical fit call: a large project can fill
    # vLLM's whole context window with prompt, leaving a reasoning model no
    # room to answer -- a confirmed live failure mode on this endpoint.
    #
    # max_tokens is double suggest_dashboard's: this endpoint emits up to
    # `desired` (>= 3) full plans in one JSON response, not one -- 2048
    # matched suggest_dashboard's single-plan budget but was confirmed live
    # to truncate a multi-widget request here (5 named charts came back as
    # 2 widgets even once the prompt-trimming fix landed and context
    # trimming was ruled out; a 1-widget isolated request of the same shape
    # succeeded fully). _repair_truncated_json silently salvages whatever
    # completed before the cutoff, so a too-small budget here looks
    # identical to bad grounding rather than what it actually is: the
    # response ran out of room mid-plan.
    logger.info(
        "dashboard suggest-multi prompt len=%d (pre-fit) tenant=%s project=%s",
        len(prompt), req.tenant_id, req.project_id,
    )
    prompt = _fit_plan_prompt(
        prompt, _DASHBOARD_INSIGHT_SYSTEM_PROMPT, max_tokens=4096
    )
    logger.info(
        "dashboard suggest-multi prompt len=%d (post-fit) tenant=%s project=%s",
        len(prompt), req.tenant_id, req.project_id,
    )
    raw = await llm_client.generate(
        prompt=prompt,
        system_prompt=_DASHBOARD_INSIGHT_SYSTEM_PROMPT,
        model=req.model or settings.sql_model,
        temperature=0.4,
        max_tokens=4096,
        num_ctx=24576,
        response_format="json",
        llm_target_url=req.llm_target_url,
    )

    parsed = _parse_json_response(raw)
    raw_suggestions: list[dict] = []
    if isinstance(parsed, dict):
        if isinstance(parsed.get("suggestions"), list):
            raw_suggestions = [s for s in parsed["suggestions"] if isinstance(s, dict)]
        else:
            raw_suggestions = [parsed]
    elif isinstance(parsed, list):
        raw_suggestions = [s for s in parsed if isinstance(s, dict)]
    else:
        logger.warning("Failed to parse dashboard plans: %s", raw[:200])

    allowed_set = {t.lower() for t in allowed_tables}
    suggestions: list[DashboardPlanSuggestion] = []
    for s in raw_suggestions:
        widgets: list[DashboardPlanWidget] = []
        for w in s.get("widgets", []):
            if not isinstance(w, dict):
                continue
            sql = (w.get("sql") or "").strip()
            if sql:
                # Clean + validate against the allowed tables. Drop widgets whose
                # SQL references tables outside the project (hallucinated/reference
                # docs); narrative widgets (empty sql) are always kept.
                sql = _ensure_group_by(_clean_sql(sql))
                try:
                    validate_sql(sql, allowed_tables)
                except SQLValidationError as e:
                    logger.warning(
                        "Dropping multi-suggest widget %r: %s",
                        w.get("title", "untitled"), e.reason,
                    )
                    continue
            widgets.append(
                DashboardPlanWidget(
                    title=str(w.get("title", "")),
                    chart_type=str(w.get("chart_type") or w.get("type") or ""),
                    business_question=str(w.get("business_question", "")),
                    sql=sql,
                    label_column=str(w.get("label_column", "")),
                    value_column=str(w.get("value_column", "")),
                )
            )
        # Keep only data sources that are real allowed tables (drop hallucinations
        # and any reference document the planner may have slipped in).
        data_sources = [
            str(d)
            for d in s.get("data_sources", [])
            if str(d).lower() in allowed_set
        ]
        suggestions.append(
            DashboardPlanSuggestion(
                title=str(s.get("title") or "AI Dashboard"),
                description=str(s.get("description", "")),
                business_purpose=str(s.get("business_purpose", "")),
                audience=str(s.get("audience") or req.audience or ""),
                widgets=widgets,
                kpis=[str(k) for k in s.get("kpis", []) if k],
                data_sources=data_sources,
                confidence=float(s.get("confidence") or 0.0),
                quality_score=int(s.get("quality_score") or 0),
            )
        )

    update_activity(req.user_id, req.tenant_id, req.project_id)

    return SuggestDashboardsMultiResponse(
        suggestions=suggestions,
        request_id=request_id,
        model_used=req.model or settings.sql_model,
    )
