"""Conversational analytics orchestration.

Submits analytical turns, classifies intent, delegates SQL generation/execution
to the existing ask-and-run core, applies chart-only changes, and persists the
conversation state so follow-ups can reuse prior successful results.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.models.analytics_conversation import AnalyticsConversation, AnalyticsConversationTurn
from app.routes.ai_proxy import _ask_and_run_core
from app.services.ai_governance import ai_governance_service, infer_governance_key
from app.services.project_ai_context import build_project_ai_context

logger = logging.getLogger(__name__)

_MAX_PREVIEW_ROWS = 200
_MAX_PREVIEW_BYTES = 1024 * 1024


class ConversationalIntent(str):
    NEW_ANALYSIS = "new_analysis"
    QUERY_CHANGE = "query_change"
    CHART_CHANGE = "chart_change"
    EXPLAIN = "explain"
    CLARIFICATION = "clarification"
    UNSUPPORTED = "unsupported"


# Deterministic chart-only signals. More specific patterns first.
_CHART_CHANGE_SIGNALS = [
    (r"\bchange\s+(?:it|this|the chart)\s+(?:to|into|as)\s+(?:a\s+)?(bar|line|pie|table|scatter|donut|area|horizontal\s+bar|stacked\s+bar|grouped\s+bar)", "chart_type"),
    (r"\bmake\s+(?:it|this)\s+(?:a\s+)?(bar|line|pie|table|scatter|donut|area|horizontal)\b", "chart_type"),
    (r"\bshow\s+(?:it|this)\s+as\s+(?:a\s+)?(bar|line|pie|table|scatter|donut|area)\b", "chart_type"),
    (r"\b(use|make)\s+(\w+)\s+(?:the\s+)?x[- ]?axis\b", "label_column"),
    (r"\b(use|make)\s+(\w+)\s+(?:the\s+)?label\b", "label_column"),
    (r"\b(use|make)\s+(\w+)\s+(?:the\s+)?(value|y[- ]?axis|series)\b", "value_column"),
    (r"\badd\s+(\w+)\s+as\s+(?:a\s+)?(?:second|another|new)\s+(?:series|value|metric)\b", "add_value"),
    (r"\b(add|show)\s+data\s+labels\b", "data_labels_on"),
    (r"\b(hide|remove)\s+data\s+labels\b", "data_labels_off"),
    (r"\b(sort|order)\s+(?:by\s+)?value\s+(?:highest|descending|desc|low to high)\b", "sort_desc"),
    (r"\b(sort|order)\s+(?:by\s+)?value\s+(?:lowest|ascending|asc|high to low)\b", "sort_asc"),
    (r"\b(sort|order)\s+(?:by\s+)?label\s+(?:a[- ]?z|ascending|asc)\b", "sort_label_asc"),
    (r"\b(sort|order)\s+(?:by\s+)?label\s+(?:z[- ]?a|descending|desc)\b", "sort_label_desc"),
    (r"\bshow\s+(?:the\s+)?legend\b", "legend_on"),
    (r"\bhide\s+(?:the\s+)?legend\b", "legend_off"),
    (r"\bmake\s+(?:it|this)\s+horizontal\b", "horizontal"),
    (r"\bmake\s+(?:it|this)\s+vertical\b", "vertical"),
    (r"\bswitch\s+(?:to|the\s+)?(\w+)\s*chart\b", "chart_type"),
    (r"\b(chart\s+type|visualization)\s*(?:is|:|=)?\s*(bar|line|pie|table|scatter|donut|area)\b", "chart_type"),
]

_QUERY_CHANGE_SIGNALS = [
    r"\b(filter|only|just|exclude|remove|where)\b",
    r"\b(compare|compare to|versus|vs|year over year|yoy|month over month)\b",
    r"\b(add|include)\s+(?:a\s+)?(?:filter|column|metric|dimension|group by)\b",
    r"\b(group by|aggregate by|sum of|average of|count of)\b",
    r"\b(change|update|set)\s+(?:the\s+)?(date range|time period|from|to|since|last|past|previous)\b",
    r"\b(switch|change)\s+(?:the\s+)?(?:datasource|source|table)\b",
]

_EXPLAIN_SIGNALS = [
    r"\b(how did you|how do you|how was this|why|explain|show me|tell me)\s+(?:calculate|compute|derive|get|come up with|this|the sql|sql)\b",
    r"\b(show|view|reveal)\s+(?:the\s+)?sql\b",
    r"\bexplain\s+(?:this|the result|the chart|the calculation|the query)\b",
]


def _normalize_question(question: str) -> str:
    return re.sub(r"\s+", " ", question.strip().lower())


def classify_conversational_intent(question: str, prior_turn: AnalyticsConversationTurn | None) -> tuple[str, dict[str, Any]]:
    """Classify a turn into one of the conversational intent types.

    Returns the intent and a dict of parsed chart-patch parameters when the
    intent is a chart-only change.
    """
    q = _normalize_question(question)
    chart_match, chart_params = _match_chart_change(q)
    if chart_match and prior_turn and prior_turn.result_cache:
        return ConversationalIntent.CHART_CHANGE, chart_params

    if _matches_any(q, _EXPLAIN_SIGNALS):
        return ConversationalIntent.EXPLAIN, {}

    if prior_turn is None:
        return ConversationalIntent.NEW_ANALYSIS, {}

    if _matches_any(q, _QUERY_CHANGE_SIGNALS):
        return ConversationalIntent.QUERY_CHANGE, {}

    # Fallback: if there is prior context and the question is short/ambiguous,
    # treat it as a query refinement so the engine attempts to re-execute safely.
    return ConversationalIntent.QUERY_CHANGE, {}


def _match_chart_change(q: str) -> tuple[bool, dict[str, Any]]:
    params: dict[str, Any] = {}
    for pattern, action in _CHART_CHANGE_SIGNALS:
        m = re.search(pattern, q)
        if not m:
            continue
        if action == "chart_type":
            chart_type = (m.group(1) if len(m.groups()) >= 1 else "").strip().lower()
            params["chartType"] = _map_chart_type(chart_type)
        elif action == "label_column":
            params["labelColumn"] = m.group(2).strip()
        elif action == "value_column":
            params["valueColumn"] = m.group(2).strip()
        elif action == "add_value":
            params.setdefault("addValueColumn", []).append(m.group(1).strip())
        elif action == "data_labels_on":
            params["dataLabels"] = True
        elif action == "data_labels_off":
            params["dataLabels"] = False
        elif action == "sort_desc":
            params["sort"] = {"column": "value", "direction": "desc"}
        elif action == "sort_asc":
            params["sort"] = {"column": "value", "direction": "asc"}
        elif action == "sort_label_asc":
            params["sort"] = {"column": "label", "direction": "asc"}
        elif action == "sort_label_desc":
            params["sort"] = {"column": "label", "direction": "desc"}
        elif action == "legend_on":
            params["legendVisible"] = True
        elif action == "legend_off":
            params["legendVisible"] = False
        elif action == "horizontal":
            params["subtype"] = "horizontal"
        elif action == "vertical":
            params["subtype"] = "vertical"
        return True, params
    return False, params


def _map_chart_type(raw: str) -> str:
    mapping = {
        "horizontal bar": "bar",
        "stacked bar": "bar",
        "grouped bar": "bar",
        "bar": "bar",
        "line": "line",
        "area": "line",
        "pie": "pie",
        "donut": "pie",
        "scatter": "scatter",
        "table": "table",
    }
    return mapping.get(raw, "bar")


def _matches_any(q: str, patterns: list[str]) -> bool:
    return any(re.search(p, q) for p in patterns)


def _sql_fingerprint(sql: str | None) -> str | None:
    if not sql:
        return None
    normalized = " ".join(sql.lower().split())
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def _bound_result(rows: list[dict[str, Any]], max_rows: int = _MAX_PREVIEW_ROWS, max_bytes: int = _MAX_PREVIEW_BYTES) -> tuple[list[dict[str, Any]], bool]:
    """Trim preview rows/columns to bounded limits."""
    if not rows:
        return [], False
    bounded = rows[:max_rows]
    total = json.dumps(bounded, default=str)
    while len(total.encode()) > max_bytes and len(bounded) > 1:
        bounded = bounded[: len(bounded) // 2]
        total = json.dumps(bounded, default=str)
    truncated = len(rows) > len(bounded)
    return bounded, truncated


def _profile_result(columns: list[str], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Lightweight result profiler for storage and chart recommendation."""
    if not columns or not rows:
        return {"columns": columns or [], "rowCount": 0}
    sample = rows[0]
    numeric: list[str] = []
    categorical: list[str] = []
    datetime_cols: list[str] = []
    for col in columns:
        val = sample.get(col)
        if isinstance(val, int | float):
            numeric.append(col)
        elif isinstance(val, str) and re.match(r"^\d{4}-\d{2}-\d{2}", val):
            datetime_cols.append(col)
        else:
            categorical.append(col)
    return {
        "columns": columns,
        "rowCount": len(rows),
        "numericColumns": numeric,
        "categoricalColumns": categorical,
        "datetimeColumns": datetime_cols,
    }


def _build_chart_config(suggested: dict[str, Any] | None, columns: list[str], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Normalize the ask-and-run visualization suggestion into a stable chart config."""
    if not suggested:
        suggested = {}
    chart_type = suggested.get("type") or "table"
    config: dict[str, Any] = {
        "type": chart_type,
        "title": suggested.get("title", "Chart"),
    }
    # Pick sensible defaults from result shape
    label_candidates = [c for c in columns if c.lower() in ("month", "period", "date", "category", "region", "status", "supplier", "entity")]
    value_candidates = [c for c in columns if c.lower() in ("value", "n", "metric", "revenue", "total", "count", "sum", "amount")]
    remaining = [c for c in columns if c not in label_candidates and c not in value_candidates]
    if not label_candidates and remaining:
        label_candidates = [remaining[0]]
    if not value_candidates and remaining:
        value_candidates = remaining[:1]
    if not value_candidates:
        value_candidates = columns[-1:] if columns else []
    if label_candidates:
        config["labelColumn"] = label_candidates[0]
    if value_candidates:
        config["valueColumns"] = value_candidates
    if chart_type in ("line", "bar", "scatter") and len(value_candidates) > 1:
        config["seriesColumn"] = label_candidates[0] if label_candidates else None
    return config


def apply_chart_change(chart_config: dict[str, Any], result: dict[str, Any], instruction: str) -> tuple[dict[str, Any], str]:
    """Apply a natural-language chart change to an existing config.

    Returns the updated config and a short assistant message.
    """
    chart_match, params = _match_chart_change(_normalize_question(instruction))
    if not chart_match:
        return chart_config, "I couldn't understand that chart change."

    new_config = dict(chart_config)
    columns = (result.get("columns") or []) if result else []
    value_columns = new_config.get("valueColumns") or []

    if "chartType" in params:
        new_config["type"] = params["chartType"]
    if "labelColumn" in params:
        if params["labelColumn"] in columns:
            new_config["labelColumn"] = params["labelColumn"]
        else:
            return chart_config, f"Column '{params['labelColumn']}' is not available in this result."
    if "valueColumn" in params:
        if params["valueColumn"] in columns:
            new_config["valueColumns"] = [params["valueColumn"]]
        else:
            return chart_config, f"Column '{params['valueColumn']}' is not available in this result."
    for added in params.get("addValueColumn", []):
        if added in columns and added not in value_columns:
            value_columns = [*list(value_columns), added]
            new_config["valueColumns"] = value_columns
    if "dataLabels" in params:
        new_config["dataLabels"] = params["dataLabels"]
    if "legendVisible" in params:
        new_config["legend"] = {"visible": params["legendVisible"]}
    if "sort" in params:
        new_config["sort"] = params["sort"]
    if "subtype" in params:
        new_config["subtype"] = params["subtype"]

    # Validate: pie/donut needs one value column and a label column.
    chart_type = new_config.get("type")
    if chart_type == "pie":
        if not new_config.get("labelColumn") or len(new_config.get("valueColumns", [])) != 1:
            return chart_config, "A pie chart needs one category column and one numeric value."

    message = "Updated the chart."
    if params.get("chartType"):
        message = f"Changed the chart to a {new_config['type']} chart."
    elif params.get("valueColumn"):
        message = f"Now showing {new_config['valueColumns'][0]} as the value."
    elif params.get("addValueColumn"):
        message = f"Added {', '.join(params['addValueColumn'])} as a series."
    elif params.get("labelColumn"):
        message = f"Using {new_config['labelColumn']} as the label."
    elif "dataLabels" in params:
        message = "Data labels turned {}.".format("on" if params["dataLabels"] else "off")
    elif "legendVisible" in params:
        message = "Legend turned {}.".format("on" if params["legendVisible"] else "off")
    elif params.get("sort"):
        message = f"Sorted by {params['sort']['column']} {params['sort']['direction']}."

    return new_config, message


def _build_explanation(
    sql: str | None,
    result: dict[str, Any] | None,
    chart_config: dict[str, Any] | None,
    governance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    exp: dict[str, Any] = {
        "sql": sql,
        "rowCount": (result or {}).get("rowCount") if result else None,
        "columns": (result or {}).get("columns") if result else None,
        "chartType": (chart_config or {}).get("type"),
        "generatedAt": datetime.now(UTC).isoformat(),
    }
    if governance:
        exp["governance"] = governance
    return exp


def _format_context_prompt(project_context: dict[str, Any] | None) -> str:
    """Return a concise, bounded project context block for SQL generation."""
    if not project_context or not project_context.get("ai_context_enabled"):
        return ""
    project = project_context.get("project", {})
    goals = project_context.get("goals") or []
    metrics = project_context.get("metrics") or []
    risks = project_context.get("risks") or []
    instructions = project_context.get("instructions") or ""
    interpretation = project_context.get("interpretation_notes") or ""

    parts = [
        "--- Project context ---",
        f"Project: {project.get('name', 'Unknown')}",
    ]
    if project.get("purpose"):
        parts.append(f"Purpose: {project['purpose']}")
    if project.get("business_function"):
        parts.append(f"Function: {project['business_function']}")
    if project.get("industry"):
        parts.append(f"Industry: {project['industry']}")
    if instructions:
        parts.append(f"AI guidance: {instructions}")
    if interpretation:
        parts.append(f"Interpretation notes: {interpretation}")
    if goals:
        parts.append("Goals: " + ", ".join(g["title"] for g in goals[:5] if g.get("title")))
    if metrics:
        parts.append("Metrics: " + ", ".join(m["name"] for m in metrics[:5] if m.get("name")))
    if risks:
        parts.append("Risks: " + ", ".join(r["title"] for r in risks[:5] if r.get("title")))
    parts.append("--- End project context ---")
    return "\n".join(parts)[:1200]


async def _run_analytical_turn(
    session: AsyncSession,
    context: RequestContext,
    project_id: int,
    question: str,
    prior_turn: AnalyticsConversationTurn | None,
    datasource_id: int | None,
    *,
    project_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run a data-changing turn by delegating to the existing ask-and-run core."""
    context_block = _format_context_prompt(project_context)
    # When this is a follow-up and we have prior SQL, prepend a concise context
    # line to the question so the generator can refine instead of starting from
    # scratch. The AI query endpoint treats the prompt as the full user request.
    prompt = question
    if prior_turn and prior_turn.sql:
        prompt = (
            f"{context_block}\n\n"
            f"Previous query: {prior_turn.sql}\n"
            f"User follow-up: {question}\n"
            "Generate a single, safe replacement query incorporating the follow-up."
        )
    elif context_block:
        prompt = f"{context_block}\n\nUser question: {question}"

    run = await _ask_and_run_core(
        session,
        context,
        project_id=project_id,
        question=prompt,
        max_rows=_MAX_PREVIEW_ROWS,
        source=None,  # source override can be added once the route exposes it
    )
    return run


async def execute_turn(
    session: AsyncSession,
    context: RequestContext,
    conversation: AnalyticsConversation,
    turn: AnalyticsConversationTurn,
    *,
    datasource_id: int | None = None,
) -> None:
    """Execute a single turn and mutate its persisted fields in place.

    The turn's status, SQL, result cache, chart config, and explanation are
    updated. For data-changing turns, the existing ask-and-run core is used.
    For chart-only turns, no SQL is executed and the prior result is reused.
    """
    prior_turn: AnalyticsConversationTurn | None = None
    if conversation.last_successful_turn_id is not None:
        prior_turn = await session.get(AnalyticsConversationTurn, conversation.last_successful_turn_id)
    question = turn.user_message

    intent, chart_params = classify_conversational_intent(question, prior_turn)
    turn.intent_type = intent

    if intent == ConversationalIntent.CHART_CHANGE:
        if prior_turn is None or prior_turn.result_cache is None:
            turn.status = "error"
            turn.error_code = "no_prior_result"
            turn.assistant_message = "There is no previous result to change the chart for."
            return

        result_cache = prior_turn.result_cache or {}
        chart_config = dict(prior_turn.chart_config or _build_chart_config(
            result_cache.get("suggestedVisualization"),
            result_cache.get("columns", []),
            result_cache.get("rows", []),
        ))
        new_config, message = apply_chart_change(chart_config, result_cache, question)
        turn.chart_config = new_config
        turn.result_cache = result_cache
        turn.sql = prior_turn.sql
        turn.assistant_message = message
        turn.status = "success"
        return

    if intent == ConversationalIntent.EXPLAIN:
        if prior_turn is None:
            turn.status = "error"
            turn.error_code = "no_prior_result"
            turn.assistant_message = "There is nothing to explain yet."
            return
        turn.sql = prior_turn.sql
        turn.result_cache = prior_turn.result_cache
        turn.chart_config = prior_turn.chart_config
        turn.explanation = prior_turn.explanation or _build_explanation(
            prior_turn.sql, prior_turn.result_cache, prior_turn.chart_config
        )
        turn.assistant_message = (
            "This result was generated from the following SQL: "
            f"{prior_turn.sql or 'No SQL available.'}"
        )
        turn.status = "success"
        return

    # New analysis or query-changing follow-up
    project_id = conversation.project_id
    if project_id is None:
        turn.status = "error"
        turn.error_code = "no_project"
        turn.assistant_message = "This conversation is not attached to a project."
        return

    project_context: dict[str, Any] | None = None
    try:
        project_context = await build_project_ai_context(
            session,
            tenant_id=context.tenant_id,
            project_id=project_id,
            request_type="conversational_analytics",
        )
    except Exception as exc:
        logger.warning("Failed to build project context for conversation %s: %s", conversation.id, exc)

    # Pre-execution governance check: block obvious high-risk or disabled methods
    # before any SQL is generated for this turn.
    pre_method = infer_governance_key(question=question)
    pre_decision = await ai_governance_service.evaluate_method(
        session,
        context.tenant_id,
        pre_method,
        project_id=project_id,
        conversation_id=conversation.id,
        turn_id=turn.id,
        actor_user_id=context.user_id,
    )
    if not pre_decision.allowed:
        turn.status = "error"
        turn.error_code = "ai_governance_blocked"
        turn.assistant_message = pre_decision.user_message
        return

    run = await _run_analytical_turn(
        session,
        context,
        project_id,
        question,
        prior_turn,
        datasource_id,
        project_context=project_context,
    )

    turn.sql = run.get("sql") or None
    turn.project_context_version = project_context.get("version") if project_context else None
    turn.sql_fingerprint = _sql_fingerprint(turn.sql)

    if run.get("status") != "success" or not run.get("rows"):
        turn.status = "error"
        turn.error_code = run.get("status", "unknown")
        turn.assistant_message = run.get("error") or "I could not answer that question with the available data."
        turn.result_metadata = {"error": run.get("error"), "errorDetails": run.get("errorDetails")}
        return

    columns = run.get("columns", [])
    raw_rows = run.get("rows", [])
    bounded_rows, truncated = _bound_result(raw_rows)
    profile = _profile_result(columns, bounded_rows)
    result_cache = {
        "columns": columns,
        "rows": bounded_rows,
        "rowCount": profile["rowCount"],
        "truncated": truncated,
        "truncatedTo": len(bounded_rows) if truncated else None,
        "suggestedVisualization": run.get("suggestedVisualization"),
    }
    chart_config = _build_chart_config(run.get("suggestedVisualization"), columns, bounded_rows)

    # Post-execution governance check against the generated SQL/chart.  If the AI
    # produced a disabled analytical method, surface a governed message instead of
    # the result.
    post_method = infer_governance_key(
        question=question,
        chart_type=chart_config.get("type"),
        sql=turn.sql,
    )
    post_decision = await ai_governance_service.evaluate_method(
        session,
        context.tenant_id,
        post_method,
        project_id=project_id,
        conversation_id=conversation.id,
        turn_id=turn.id,
        actor_user_id=context.user_id,
    )
    if not post_decision.allowed:
        turn.status = "error"
        turn.error_code = "ai_governance_blocked"
        turn.assistant_message = post_decision.user_message
        return

    turn.result_cache = result_cache
    turn.result_metadata = profile
    turn.chart_config = chart_config
    turn.explanation = _build_explanation(
        turn.sql, result_cache, chart_config, governance=post_decision.to_explanation_dict()
    )
    turn.datasource_context = {"dataSourcesUsed": run.get("dataSourcesUsed", [])}
    turn.assistant_message = run.get("explanation") or "Here is the result."
    turn.status = "success"
