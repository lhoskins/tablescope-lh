"""The ``/ai/intelligence/plan`` endpoint."""

import logging
import uuid

from fastapi import APIRouter, HTTPException, status

from app.core.activity import update_activity
from app.core.config import settings
from app.core.security import verify_signature
from app.models.schemas import (
    IntelligencePlanRequest,
    IntelligencePlanResponse,
    PlannedAnalysis,
)
from app.services import chart_catalog, context_builder, llm_client
from app.services.context_builder import ContextBuildError
from app.services.sql_validator import SQLValidationError, validate_sql

from .ai_plan_prompt import (
    _build_kg_hypothesis_lines,
    _build_relationship_floor_line,
    _build_relationship_hint_lines,
)
from .ai_plan_sql import (
    _ensure_group_by,
    _ensure_join_on_clause,
    _join_tables_are_evidence_backed,
    _qualify_bare_shared_columns,
    _sql_table_count,
)
from .ai_shared import (
    _INTEL_SYSTEM_PROMPT,
    _TEIID_JOIN_EXCEPTION_RULE,
    _TEIID_RULES_COMMON,
    _TEIID_RULES_HEADER,
    _TEIID_SQL_RULES,
    _build_schema_lines,
    _clean_sql,
    _infer_chart_columns,
    _parse_json_response,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _fit_plan_prompt(
    prompt: str,
    system_prompt: str,
    *,
    max_model_len: int = 8192,
    max_tokens: int = 2048,
    chars_per_token: float = 3.5,
) -> str:
    """Trim the front of the user prompt so system + prompt + output fit vLLM."""
    reserve_tokens = max_tokens + int(len(system_prompt) / chars_per_token) + 40
    token_budget = max(0, max_model_len - reserve_tokens)
    char_budget = int(token_budget * chars_per_token)
    if len(prompt) <= char_budget:
        return prompt
    # Keep the instruction/output-format tail and drop excess context from the front.
    truncated = prompt[-char_budget:]
    idx = truncated.find("\n")
    if idx != -1 and idx < 120:
        truncated = truncated[idx + 1 :]
    return "[context truncated for length]\n\n" + truncated


# Chart families the planner may request. These map onto the dashboard's chart
# catalog downstream (platform-api ``_build_chart``); the result shape can still
# override the pick (e.g. a single-row aggregate always renders as KPI tiles).
# Chart vocabulary is markdown-driven (chart_selection_best_practices.md via
# app.services.chart_catalog) — do not hard-code chart-type enums here. The
# platform's visualization engine shape-validates and re-ranks every proposal.
def _allowed_plan_chart_types() -> frozenset[str]:
    return chart_catalog.allowed_plan_chart_types()


@router.post("/intelligence/plan", response_model=IntelligencePlanResponse)
async def intelligence_plan(req: IntelligencePlanRequest) -> IntelligencePlanResponse:
    """Propose high-value diagnostic analyses for a project (SQL written in memory).

    The LLM reasons over the project's real schema + documents and returns a set
    of analyses, each with a category (risk/trend/opportunity), a business
    rationale, and either a read-only SQL query or a document-based finding.
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
            feature="intelligence_plan",
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

    doc_lines = ""
    if req.documents:
        project_docs = [
            d for d in req.documents if d.get("source") != "reference_library"
        ]
        reference_docs = [
            d for d in req.documents if d.get("source") == "reference_library"
        ]
        sections: list[str] = []
        if project_docs:
            sections.append(
                "\nProject documents (title — summary — tags):\n"
                + "\n".join(
                    f"  - {d.get('title', 'document')}: "
                    f"{(d.get('summary') or '')[:300]}"
                    + (
                        f"  [tags: {', '.join(d.get('tags', []))}]"
                        if d.get("tags")
                        else ""
                    )
                    for d in project_docs[:20]
                )
            )
        if reference_docs:
            sections.append(
                "\nReference Library — authoritative standards, regulations, "
                "and governance policies that apply to this project. Treat "
                "these as the source of truth for compliance requirements, "
                "thresholds, and best practices. When the project's data can "
                "be assessed against one of these, propose a finding that "
                "grounds the risk/opportunity in the standard and ALWAYS put "
                "the document's exact title in source_documents:\n"
                + "\n".join(
                    f"  - {d.get('title', 'document')}"
                    + (
                        " ["
                        + ", ".join(
                            p
                            for p in (
                                d.get("issuing_body") or "",
                                d.get("tier") or "",
                            )
                            if p
                        )
                        + "]"
                        if (d.get("issuing_body") or d.get("tier"))
                        else ""
                    )
                    + f": {(d.get('summary') or '')[:300]}"
                    for d in reference_docs[:25]
                )
            )
        doc_lines = "".join(sections)

    schema_lines = _build_schema_lines(req.table_schema)
    relationship_lines = _build_relationship_hint_lines(req.relationship_hints)
    kg_lines = _build_kg_hypothesis_lines(req.knowledge_graph_context)
    # With relationship evidence in play, the flat "Do NOT write JOINs" rule
    # would contradict (and, sitting later in the prompt, override) the
    # cross-table mandate — swap in the exception-aware variant. Without
    # evidence the rules are byte-identical to the single-table original.
    teiid_rules = (
        _TEIID_RULES_HEADER + _TEIID_JOIN_EXCEPTION_RULE + _TEIID_RULES_COMMON
        if relationship_lines
        else _TEIID_SQL_RULES
    )

    # Granularity (1 executive .. 5 granular) steers count + depth + how
    # aggressively to surface smaller, lower-severity signals.
    granularity = max(1, min(5, req.granularity))
    target_count = max(1, min(req.max_analyses, {1: 3, 2: 5, 3: 8, 4: 11, 5: 15}[granularity]))
    # Cross-table analyses per evidence pair: executive levels get the single
    # strongest comparison per pair; balanced/granular levels may develop two
    # genuinely different insights on the same verified join.
    per_pair = 1 if granularity <= 2 else 2
    if granularity <= 2:
        depth_guidance = (
            "Operate at an EXECUTIVE level. Surface ONLY the few most material, "
            "highest-leverage findings — the ones a CEO would act on. Aggregate "
            "broadly; ignore minor or niche signals. Prefer high-severity items."
        )
    elif granularity >= 4:
        depth_guidance = (
            "Operate at a GRANULAR, analyst level. Drill into specific segments, "
            "categories, suppliers, time periods, or line items. Surface detailed "
            "and smaller signals too, including lower-severity 'watch' items and "
            "early-stage opportunities — even when the dataset is small. Slice the "
            "data multiple ways to find detail-level risks and opportunities."
        )
    else:
        depth_guidance = (
            "Operate at a BALANCED level — a mix of strategic headline findings "
            "and a few more specific, detailed insights."
        )

    relationship_floor = _build_relationship_floor_line(
        bool(relationship_lines), granularity
    )

    # Section order matters: schema and RELATIONSHIP EVIDENCE stay contiguous
    # and the KG hypotheses come after them, closest to the instructions, so
    # advisory graph context can never separate the evidence from the rules
    # that reference it.
    prompt = (
        f"{context_text}\n{doc_lines}\n{schema_lines}\n{relationship_lines}\n{kg_lines}\n"
        f"Allowed tables (use ONLY these, exact names): {', '.join(allowed_tables)}\n\n"
        f"{teiid_rules}\n"
        f"{depth_guidance}\n\n"
        f"Propose up to {target_count} of the most valuable analyses for this "
        "project at this level of detail. Cover a mix of risks, trends, "
        "opportunities, and relationships where the data supports it. "
        f"{relationship_floor}"
        "Each "
        "analysis must be answerable from the allowed tables OR grounded in a "
        "listed document.\n"
        + (
            "IN ADDITION to those, propose "
            + (
                "one CROSS-TABLE analysis"
                if per_pair == 1
                else "one CROSS-TABLE analysis — or TWO genuinely different "
                "ones when the pair's data supports both —"
            )
            + " for EACH table pair listed in RELATIONSHIP EVIDENCE whose "
            "data supports a genuine insight. Cross-table analyses are extra "
            f"— they do NOT count toward the {target_count} limit, and you "
            "must not drop a supportable evidence pair to stay under it.\n\n"
        ) +
        "RELATIONSHIP ANALYSES (category \"relationship\"):\n"
        "In addition to single-metric risks/trends/opportunities, actively look "
        "for pairs of columns within ONE allowed table whose relationship to each "
        "other changes over time — not just two values that both move, but a "
        "connection that strengthens, weakens, decouples, inverts, or diverges. "
        "Examples of what counts: a cost metric and a quality metric that used to "
        "track together but no longer do; one category's share of a total "
        "shrinking while another grows; a rate (e.g. defects per unit) drifting "
        "away from its historical band. The two variables may be columns on "
        "the SAME table, or on TWO tables joined per the CROSS-TABLE rules "
        "below.\n"
        "CROSS-TABLE ANALYSES (category \"relationship\"):\n"
        + (
            "For each pair in the RELATIONSHIP EVIDENCE list above, propose "
            + (
                "one analysis"
                if per_pair == 1
                else "one analysis — or two that answer genuinely different "
                "business questions —"
            )
            + " that JOINs exactly that pair on exactly the listed keys. "
        ) +
        "Write ONE flat SELECT: JOIN the two tables directly, GROUP BY label "
        "columns from the entity/master side, and aggregate ONLY numeric "
        "columns from the detail/fact side (never SUM/AVG a master-side "
        "number after the join — row fan-out inflates it). Example shape:\n"
        'SELECT s."SupplierName" AS Supplier, '
        'SUM(CAST(i."DefectQty" AS double)) AS TotalDefects '
        'FROM "Inspections" i JOIN "Suppliers" s '
        'ON i."SupplierID" = s."SupplierID" '
        'GROUP BY s."SupplierName" ORDER BY TotalDefects DESC\n'
        "Prefer the highest-confidence pairs first and skip a pair only "
        "when its data genuinely supports no insight (e.g. the joined result "
        "would be a single row or empty). Never join a pair that is not "
        "listed, and never join on matching column names that are not listed "
        "there.\n"
        "For each relationship analysis, decide which shape best reveals the "
        "change and choose accordingly:\n"
        "- If both variables are naturally plotted on a shared timeline → use "
        "'dual_line' (two series, one time axis).\n"
        "- If the relationship is better expressed as a single derived value per "
        "period (a gap, ratio, or delta between the two variables) → use 'line' "
        "and compute that derived value in the SQL itself (e.g. SELECT period, "
        "(metric_a - metric_b) AS variance).\n"
        "- If the relationship is best seen as a small number of snapshots in time "
        "rather than a continuous trend → use 'scatter' or 'bubble', with one "
        "point per period and the two variables as x/y (and a third metric as "
        "bubble size, if relevant).\n"
        "Only propose a relationship analysis when at least 3 time periods of data "
        "are available for both variables — a 2-point comparison cannot show a "
        "changing relationship.\n"
        "MANDATORY SQL SHAPE for every dual_line / scatter / time-based "
        "relationship — get this exactly right or the chart cannot be drawn:\n"
        "0. Choose your source, then stay strictly inside it:\n"
        "   (a) SINGLE TABLE — preferred when one table itself lists BOTH "
        "metric columns you want (and a date column when plotting over time). "
        "Every column you reference — both metrics, the date, anything in "
        "WHERE/GROUP BY — MUST appear under that exact table in the schema "
        "above. The Inspections-style table that holds two numeric quantities "
        "(e.g. a received quantity and a defect quantity) is usually the best "
        "single source.\n"
        "   (b) VERIFIED TWO-TABLE JOIN — when the two metrics live in "
        "DIFFERENT tables and that exact table pair appears in the "
        "RELATIONSHIP EVIDENCE list, write the join EXPLICITLY: FROM "
        "\"table1\" JOIN \"table2\" ON the exact listed keys. Fully qualify "
        "EVERY column with its table name, aggregate both metrics (AVG/SUM) "
        "grouped by the period expression so a one-to-many join cannot "
        "multiply rows, and reference only columns listed under those two "
        "tables.\n"
        "   NEVER mix the two: a single-table query must not select a column "
        "that belongs to a different table (e.g. do not select "
        "\"UnitsScrapped\" while selecting FROM a labor table that does not "
        "list it) — a column not listed under your FROM/JOIN tables does not "
        "exist for this query. If the pair you want is not in the "
        "RELATIONSHIP EVIDENCE list, change the analysis to columns that "
        "share a table instead of borrowing.\n"
        "1. The period/time column MUST appear in the SELECT list as the FIRST "
        "column, not only in GROUP BY. A query like 'SELECT metric_a, metric_b "
        "... GROUP BY period' is WRONG because the result then has no time axis. "
        "Write 'SELECT period_expr AS Period, agg_a AS metric_a, agg_b AS "
        "metric_b ... GROUP BY period_expr ORDER BY period_expr'.\n"
        "2. Build the period as a SORTABLE STRING label, NOT a bare numeric year "
        "(a number like 2026 renders as a meaningless '2.0K' tile). Default to "
        "MONTH granularity 'yyyy-MM' so a single year still shows a real trend; "
        "use 'yyyy' only when the data clearly spans 3+ distinct years. Derive it "
        "from the date column using the parse that matches its EXAMPLE value (see "
        "schema): a slash date like '1/19/2026' MUST use "
        "FORMATTIMESTAMP(PARSETIMESTAMP(\"DateCol\", 'M/d/yyyy'), 'yyyy-MM') — "
        "never CAST a slash date straight to date, it fails. An ISO value like "
        "'2026-01-19' uses FORMATTIMESTAMP(CAST(\"DateCol\" AS timestamp), "
        "'yyyy-MM'). Repeat the full expression in GROUP BY (no alias references) "
        "and ORDER BY it so periods are chronological.\n"
        "2b. A trend needs >= 3 distinct periods. If monthly grouping still "
        "yields < 3 periods the data is too thin for a trend — use a KPI or a "
        "category comparison instead of a line.\n"
        "2c. YEAR-OVER-YEAR: when the data spans 2+ years, compare the latest "
        "year against the prior year — put the within-year period (month 'MM' or "
        "'yyyy-MM') on the axis and either split the series by year or add the "
        "prior-year metric as value_column_2, so 'this year vs last year' is "
        "visible. With only ONE year of data, do NOT fabricate a prior-year "
        "comparison; trend by month instead.\n"
        "3. Set label_column to the period alias (e.g. \"Period\"), value_column "
        "to the first metric alias, and value_column_2 to the second metric "
        "alias. All three MUST be aliases that actually appear in your SELECT.\n"
        "4. CAST any text-backed column used in a comparison or CASE, not just in "
        "arithmetic — e.g. CASE WHEN CAST(\"DefectQty\" AS double) > 0 THEN 1 "
        "ELSE 0 END. An uncast text column in '> 0' will be rejected.\n"
        "5. Never use DATEDIFF (it is not a Teiid function). For a day count "
        "between two dates use TIMESTAMPDIFF(SQL_TSI_DAY, CAST(\"d1\" AS "
        "timestamp), CAST(\"d2\" AS timestamp)).\n"
        "Example (two metrics over time, date column whose example is a slash "
        "date like '1/19/2026'):\n"
        "SELECT FORMATTIMESTAMP(PARSETIMESTAMP(\"date_col\", 'M/d/yyyy'), "
        "'yyyy-MM') AS Period, AVG(CAST(\"metric_a\" AS double)) AS MetricA, "
        "AVG(CAST(\"metric_b\" AS double)) AS MetricB "
        "FROM \"some_table\" "
        "GROUP BY FORMATTIMESTAMP(PARSETIMESTAMP(\"date_col\", 'M/d/yyyy'), "
        "'yyyy-MM') ORDER BY Period — with label_column=Period, "
        "value_column=MetricA, value_column_2=MetricB, chart_type=dual_line.\n"
        "Example (two metrics from DIFFERENT tables via a verified join from "
        "the RELATIONSHIP EVIDENCE list, ISO month column):\n"
        "SELECT FORMATTIMESTAMP(CAST(\"t1\".\"Month\" AS timestamp), "
        "'yyyy-MM') AS Period, AVG(CAST(\"t1\".\"metric_a\" AS double)) AS "
        "MetricA, AVG(CAST(\"t2\".\"metric_b\" AS double)) AS MetricB "
        "FROM \"t1\" JOIN \"t2\" ON \"t1\".\"KeyCol\" = \"t2\".\"KeyCol\" "
        "GROUP BY FORMATTIMESTAMP(CAST(\"t1\".\"Month\" AS timestamp), "
        "'yyyy-MM') ORDER BY Period — every column qualified with its table, "
        "join keys exactly as listed in the evidence, both metrics "
        "aggregated.\n\n"
        "DOCUMENT-GROUNDED RELATIONSHIPS:\n"
        "Relationships are NOT limited to two table columns — also look for how "
        "the project's DATA relates to its DOCUMENTS, and how documents relate to "
        "each other:\n"
        "- DATA vs DOCUMENT TARGET: when a listed document states a concrete "
        "threshold, target, limit, or SLA that applies to a table metric (e.g. a "
        "policy requiring on-time delivery >= 98%, a defect rate < 2%, or a "
        "single-supplier spend cap of 30%), propose an analysis that trends the "
        "ACTUAL metric over time AND carries the document's stated value as a "
        "constant second series, so the reader sees the data tracking against the "
        "policy line. Compute the constant directly in SQL as its own column, "
        "e.g. SELECT period_expr AS Period, AVG(CAST(\"OnTimeFlag=1\" ...)) AS "
        "ActualOnTime, 98.0 AS PolicyTarget ... GROUP BY period_expr. Set "
        "chart_type=dual_line (or line), value_column=ActualOnTime, "
        "value_column_2=PolicyTarget, and ALWAYS list the source document title "
        "in source_documents. Phrase the title/rationale around whether the data "
        "meets, is converging toward, or is diverging from the documented "
        "requirement.\n"
        "- DOCUMENT-ONLY relationships: when two documents (or two requirements "
        "within one document) interact, conflict, or reinforce each other and no "
        "single table proves it, propose a narrative finding: leave sql empty, "
        "set chart_type=none, category=relationship, and list every relevant "
        "document in source_documents.\n"
        "Only assert a data-vs-document relationship when the metric the document "
        "describes can actually be computed from an allowed table; otherwise make "
        "it a document-only narrative finding.\n\n"
        "For data analyses, write a single read-only SQL query that returns a small "
        "result suitable for a chart or KPI (aggregate/group — not raw dumps), "
        "querying a single allowed table (or a verified two-table join from the "
        "RELATIONSHIP EVIDENCE list) with no other joins or subqueries. Pick the "
        "chart type that BEST represents each result — do NOT default everything "
        "to bar. This is an executive report, so vary the visuals across the full "
        "range below:\n"
        "- 'kpi_grid': one or a few headline numbers (a single-row aggregate).\n"
        "- 'line' (or 'area'): a trend over time / ordered periods.\n"
        "- 'dual_line': two related metrics plotted over the same time axis to show "
        "how their relationship shifts.\n"
        "- 'scatter': two variables compared across periods or entities, to show a "
        "changing or underlying relationship.\n"
        "- 'bubble': scatter with a third dimension encoded as point size (e.g. "
        "magnitude or volume).\n"
        "- 'bar' (or 'horizontal_bar'): compare a metric across categories / top-N.\n"
        "- 'stacked_bar': a metric across categories, broken into sub-components.\n"
        "- 'waterfall': a running total with sequential positive/negative "
        "contributions (e.g. bridge from budget to actual).\n"
        "- 'donut' (or 'pie'): parts-of-a-whole / share/mix of a total.\n"
        "- 'treemap': many categories' relative sizes.\n"
        "- 'funnel': stage-by-stage drop-off.\n"
        "- 'radar': multi-metric comparison of a few items.\n"
        "- 'heatmap': a metric across two categorical dimensions (e.g. category x "
        "time period), where magnitude is shown by color intensity.\n"
        "- 'gauge': a single metric against a target or threshold range.\n"
        "- 'bullet': a single metric vs. target with qualitative ranges "
        "(good/watch/poor).\n"
        "- 'sparkline_table': a small table of entities/rows, each with an inline "
        "trend sparkline and a current value — good for comparing many items' "
        "trajectories at once.\n"
        "- 'none': a narrative finding best told as prose with bolded figures "
        "(no chart). Use this for at least one insight when it reads better as text.\n"
        "For document-based findings, leave sql empty, set chart_type to 'none', and "
        "list the relevant document titles in source_documents.\n\n"
        "Before finalizing each analysis, sanity-check that it will actually return "
        "data:\n"
        "- Don't filter, group, or join on a specific value (a status, category, "
        "ID, or date range) unless the schema or sample context gives you a "
        "concrete reason to believe that value exists in the data. Prefer "
        "aggregations that span the full table (no risky WHERE clause) over a "
        "narrow filter you're guessing at.\n"
        "- Don't propose a time-based trend, dual_line, scatter, or relationship "
        "analysis unless the table clearly has enough distinct time periods to "
        "support it (see the minimum-periods rule above). If you're not confident "
        "the date range has enough spread, propose a non-time-based analysis on "
        "that table instead.\n"
        "- If, after this check, you're not confident a proposed analysis will "
        "return at least one meaningful row, drop it and propose a different "
        "analysis in its place — do not include an analysis you expect to come "
        "back empty, and do not fill a gap with placeholder, sample, or invented "
        "figures.\n"
        f"- Aim to deliver the full {target_count} analyses PLUS the "
        "cross-table analyses this way; if the data "
        "genuinely can't support that many non-empty analyses, return fewer rather "
        "than padding with weak or empty ones.\n\n"
        f"{chart_catalog.planner_chart_digest()}\n\n"
        "Return ONLY a JSON object: {\"analyses\": [ {\n"
        "  \"id\": \"a1\",\n"
        "  \"category\": \"risk|trend|opportunity|relationship\",\n"
        "  \"title\": \"short headline\",\n"
        "  \"rationale\": \"why this matters for the business (1 sentence)\",\n"
        "  \"sql\": \"SELECT ... (empty for document findings)\",\n"
        f"  \"chart_type\": \"{chart_catalog.plan_chart_type_enum()}\",\n"
        "  \"label_column\": \"alias used for the category/x axis\",\n"
        "  \"value_column\": \"alias used for the numeric value (primary metric, or size for bubble)\",\n"
        "  \"value_column_2\": \"alias for a second metric — used by dual_line, scatter, bubble, heatmap (color value), gauge/bullet (target). Omit/empty otherwise.\",\n"
        "  \"severity_hint\": \"critical|urgent|watch|opportunity|info\",\n"
        "  \"source_documents\": [\"doc title\"]\n"
        "} ] }\n\n"
        "OUTPUT FORMAT: respond with this JSON object and nothing else — no "
        "prose, no markdown, no headings, no numbered list, no code fences. "
        "Begin your response with { and end it with }."
    )

    # The vLLM host is currently limited to 8192 tokens, so trim the prompt
    # from the front while preserving the output-format instructions at the
    # tail. Reserve 2048 tokens for the generated JSON plan.
    prompt = _fit_plan_prompt(
        prompt, _INTEL_SYSTEM_PROMPT, max_model_len=8192, max_tokens=2048
    )
    raw = await llm_client.generate(
        prompt=prompt,
        system_prompt=_INTEL_SYSTEM_PROMPT,
        model=req.model or settings.reasoning_model,
        temperature=0.2,
        max_tokens=2048,
        num_ctx=8192,
        response_format="json",
        ollama_url=req.ollama_url,
    )

    parsed = _parse_json_response(raw)
    if parsed is None and raw:
        logger.warning(
            "intelligence plan JSON unparseable (len=%s, tail=%r) — "
            "attempting truncation salvage",
            len(raw), raw[-80:],
        )
    analyses: list[PlannedAnalysis] = []
    # Cross-table analyses are additive: reserve per_pair slots per evidence
    # pair on top of target_count. When the model overproduces, single-table
    # and cross-table analyses each compete only for their OWN budget — a
    # blind head-slice would cut mandated joins from the tail whenever the
    # model over-delivered single-table analyses first.
    join_budget = per_pair * len(req.relationship_hints or [])
    plan_budget = target_count + join_budget
    if parsed and isinstance(parsed.get("analyses"), list):
        raw_items = [a for a in parsed["analyses"] if isinstance(a, dict)]
        if len(raw_items) > plan_budget:
            selected: list[dict] = []
            kept_single = kept_cross = 0
            for a in raw_items:
                if _sql_table_count(a.get("sql", "") or "", allowed_tables) >= 2:
                    if kept_cross < join_budget:
                        selected.append(a)
                        kept_cross += 1
                elif kept_single < target_count:
                    selected.append(a)
                    kept_single += 1
            raw_items = selected
        for i, a in enumerate(raw_items):
            sql = _clean_sql(a.get("sql", "") or "")
            if sql:
                sql = _ensure_join_on_clause(
                    sql, req.relationship_hints or [], allowed_tables
                )
                sql = _qualify_bare_shared_columns(
                    sql, req.table_schema or None
                )
                sql = _ensure_group_by(sql)
                try:
                    validate_sql(sql, allowed_tables)
                except SQLValidationError as e:
                    logger.warning("Dropping analysis %s: %s", a.get("title"), e.reason)
                    continue
            category = str(a.get("category", "trend")).lower()
            if category not in ("risk", "trend", "opportunity", "relationship"):
                category = "trend"
            chart_type = str(a.get("chart_type", "bar")).lower()
            if chart_type not in _allowed_plan_chart_types():
                # Unknown proposal: keep planning but let the platform's
                # shape-driven ranker choose the family (it re-ranks every
                # card); "bar" only as the absolute last resort so legacy
                # consumers that require a type keep working.
                logger.info(
                    "Plan chart_type %r not in catalog; deferring to shape ranker",
                    chart_type,
                )
                chart_type = "bar"

            label_col, value_col, value2_col = _infer_chart_columns(sql)
            if chart_type in ("dual_line", "scatter"):
                if not value_col or not value2_col:
                    logger.warning(
                        "Dropping analysis %s: %s requires two measures",
                        a.get("title"),
                        chart_type,
                    )
                    continue
                a["value_column"] = value_col
                a["value_column_2"] = value2_col
                a["label_column"] = label_col or a.get("label_column", "")
            elif chart_type == "line" and value_col:
                a["value_column"] = value_col
                a["label_column"] = label_col or a.get("label_column", "")

            if (
                category == "relationship"
                and chart_type in ("dual_line", "scatter")
                and _sql_table_count(sql, allowed_tables) < 2
            ):
                logger.warning(
                    "Dropping analysis %s: relationship %s must be multi-table",
                    a.get("title"),
                    chart_type,
                )
                continue
            if sql and _sql_table_count(sql, allowed_tables) >= 2:
                backed, _pair, hint = _join_tables_are_evidence_backed(
                    sql, req.relationship_hints or []
                )
                if not backed:
                    logger.warning(
                        "Dropping analysis %s: join pair not in relationship evidence",
                        a.get("title"),
                    )
                    continue
                if chart_type == "dual_line" and hint and hint.get("grain_mismatch"):
                    logger.warning(
                        "Dropping analysis %s: dual_line join on grain-mismatched pair",
                        a.get("title"),
                    )
                    continue
            # An analysis must have either runnable SQL or document grounding.
            if not sql and not a.get("source_documents"):
                continue
            analyses.append(
                PlannedAnalysis(
                    id=str(a.get("id") or f"a{i + 1}"),
                    category=category,
                    title=str(a.get("title", "")),
                    rationale=str(a.get("rationale", "")),
                    sql=sql,
                    chart_type=chart_type,
                    label_column=str(a.get("label_column", "")),
                    value_column=str(a.get("value_column", "")),
                    value_column_2=str(a.get("value_column_2", "")),
                    severity_hint=str(a.get("severity_hint", "watch")),
                    source_documents=[
                        str(d) for d in a.get("source_documents", []) if d
                    ],
                )
            )
    else:
        logger.warning("Failed to parse intelligence plan: %s", raw[:200])

    update_activity(req.user_id, req.tenant_id, req.project_id)
    return IntelligencePlanResponse(
        analyses=analyses,
        request_id=request_id,
        model_used=req.model or settings.reasoning_model,
    )
