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
from app.services import ai_intelligence_client

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


# Closed chart vocabulary enforced by the platform. The LLM may propose any
# type/subtype in this list; the platform validates the patch against the real
# result columns before it is persisted.
_CHART_TYPES = frozenset(
    {
        "bar",
        "line",
        "area",
        "pie",
        "scatter",
        "combo",
        "radar",
        "radial_bar",
        "treemap",
        "funnel",
        "sankey",
        "kpi",
        "table",
    }
)

_CHART_SUBTYPES: dict[str, frozenset[str]] = {
    "bar": frozenset({"column", "stacked_bar", "grouped_bar", "horizontal_bar", "stacked_horizontal"}),
    "line": frozenset({"", "smooth_line"}),
    "area": frozenset({"", "stacked_area"}),
    "pie": frozenset({"", "donut"}),
    "scatter": frozenset({"", "bubble"}),
    "combo": frozenset({"bar_line"}),
    "radar": frozenset({"", "scorecard"}),
    "radial_bar": frozenset({"", "multi_ring"}),
    "treemap": frozenset(),
    "funnel": frozenset(),
    "sankey": frozenset(),
    "kpi": frozenset(),
    "table": frozenset(),
}

# Minimal degraded-mode signals used only when the AI server is disabled or
# unreachable. They are intentionally tiny so the feature never hard-fails.
_FALLBACK_CHART_CONTEXT = re.compile(
    r"\b(chart|graph|plot|format|visuali[sz]e|reformat|"
    r"change\s+.*\s+to|make\s+.*\s+a|show\s+.*\s+as|"
    r"switch\s+(?:to|the)|convert|run\s+.*\s+using|use\s+.*\s+format|as\s+a)\b"
)
_FALLBACK_EXPLAIN = re.compile(
    r"\b(explain|why|how\s+did\s+you|how\s+do\s+you|how\s+was\s+this|"
    r"show\s+me\s+the\s+sql|what\s+sql|tell\s+me\s+how)\b"
)


def _normalize_question(question: str) -> str:
    return re.sub(r"\s+", " ", question.strip().lower())


def _prior_turn_state(prior_turn: AnalyticsConversationTurn | None) -> dict[str, Any]:
    """Return grounded state for the LLM classifier."""
    if prior_turn is None:
        return {"has_prior_result": False}
    result_cache = prior_turn.result_cache or {}
    result_metadata = prior_turn.result_metadata or {}
    return {
        "has_prior_result": bool(result_cache or prior_turn.sql),
        "prior_sql": prior_turn.sql or "",
        "result_columns": result_metadata.get("columns")
        or result_cache.get("columns")
        or [],
        "numeric_columns": result_metadata.get("numericColumns") or [],
        "categorical_columns": result_metadata.get("categoricalColumns") or [],
        "row_count": result_metadata.get("rowCount")
        or result_cache.get("rowCount")
        or 0,
        "current_chart": prior_turn.chart_config or {},
    }


async def classify_turn(
    question: str,
    prior_turn: AnalyticsConversationTurn | None,
    *,
    tenant_id: int,
    user_id: int,
    project_id: int | None,
) -> tuple[str, dict[str, Any]]:
    """Classify a turn LLM-first; degrade deterministically when AI is off."""
    state = _prior_turn_state(prior_turn)
    valid_intents = {
        ConversationalIntent.NEW_ANALYSIS,
        ConversationalIntent.QUERY_CHANGE,
        ConversationalIntent.CHART_CHANGE,
        ConversationalIntent.EXPLAIN,
        ConversationalIntent.CLARIFICATION,
        ConversationalIntent.UNSUPPORTED,
    }

    if ai_intelligence_client.is_enabled() and project_id is not None:
        try:
            decision = await ai_intelligence_client.classify_conversation_turn(
                tenant_id=tenant_id,
                user_id=user_id,
                project_id=project_id,
                message=question,
                **state,
            )
        except ai_intelligence_client.AIUnavailableError as exc:
            logger.warning("Conversation-turn classifier unavailable: %s", exc)
            decision = None
        else:
            if decision:
                intent = str(decision.get("intent") or "").strip().lower()
                if intent in valid_intents:
                    if intent in {ConversationalIntent.CHART_CHANGE, ConversationalIntent.EXPLAIN} and not state["has_prior_result"]:
                        intent = ConversationalIntent.NEW_ANALYSIS
                    chart = decision.get("chart") or {} if intent == ConversationalIntent.CHART_CHANGE else {}
                    return intent, chart

    return _fallback_classify(question, prior_turn)


def _fallback_classify(
    question: str, prior_turn: AnalyticsConversationTurn | None
) -> tuple[str, dict[str, Any]]:
    """Minimal deterministic classifier for degraded mode (AI off/unreachable)."""
    q = _normalize_question(question)

    if prior_turn is None or not (prior_turn.result_cache or prior_turn.sql):
        return ConversationalIntent.NEW_ANALYSIS, {}

    if _FALLBACK_EXPLAIN.search(q) and prior_turn.result_cache:
        return ConversationalIntent.EXPLAIN, {}

    if _FALLBACK_CHART_CONTEXT.search(q) and prior_turn.result_cache:
        patch = _crude_chart_patch(q)
        if patch:
            return ConversationalIntent.CHART_CHANGE, patch

    return ConversationalIntent.QUERY_CHANGE, {}


def _crude_chart_patch(q: str) -> dict[str, Any]:
    """Tiny regex-free mapping for degraded-mode chart reformatting."""
    mappings = [
        ("horizontal bar", {"type": "bar", "subtype": "horizontal_bar"}),
        ("stacked horizontal", {"type": "bar", "subtype": "stacked_horizontal"}),
        ("stacked bar", {"type": "bar", "subtype": "stacked_bar"}),
        ("grouped bar", {"type": "bar", "subtype": "grouped_bar"}),
        ("bar", {"type": "bar"}),
        ("column", {"type": "bar", "subtype": "column"}),
        ("line", {"type": "line"}),
        ("area", {"type": "area"}),
        ("donut", {"type": "pie", "subtype": "donut"}),
        ("pie", {"type": "pie"}),
        ("table", {"type": "table"}),
        ("scatter", {"type": "scatter"}),
    ]
    for phrase, patch in mappings:
        if phrase in q:
            return patch
    # Ambiguous but clearly chart-related: default to a plain bar chart.
    if re.search(r"\b(chart|graph|plot|format)\b", q):
        return {"type": "bar"}
    return {}


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


def _patch_message(applied: list[str], new_config: dict[str, Any]) -> str:
    """Return a short assistant message describing the applied chart patch."""
    if not applied:
        return "Updated the chart."

    if "type" in applied or "subtype" in applied:
        chart_type = new_config.get("type", "bar")
        subtype = new_config.get("subtype")
        style = chart_type
        if subtype == "horizontal_bar":
            style = "horizontal bar"
        elif subtype == "stacked_bar":
            style = "stacked bar"
        elif subtype == "grouped_bar":
            style = "grouped bar"
        elif subtype == "stacked_horizontal":
            style = "stacked horizontal bar"
        elif subtype == "donut":
            style = "donut"
        elif subtype == "smooth_line":
            style = "smooth line"
        elif subtype == "stacked_area":
            style = "stacked area"
        elif subtype == "bubble":
            style = "bubble"
        elif subtype == "bar_line":
            style = "bar + line"
        elif subtype == "scorecard":
            style = "scorecard"
        elif subtype == "multi_ring":
            style = "multi-ring"
        return f"Changed the chart to a {style} chart."

    if "label" in applied:
        return f"Using {new_config['labelColumn']} as the label."
    if "values" in applied:
        return f"Now showing {', '.join(new_config['valueColumns'])} as the value(s)."
    if "sort" in applied:
        sort = new_config["sort"]
        return f"Sorted by {sort['column']} {sort['direction']}."
    if "data labels" in applied:
        return f"Data labels turned {'on' if new_config['dataLabels'] else 'off'}."
    if "legend" in applied:
        visible = new_config.get("legend", {}).get("visible")
        return f"Legend turned {'on' if visible else 'off'}."
    if "title" in applied:
        return f"Updated chart title to '{new_config['title']}'."

    return "Updated the chart."


def apply_chart_patch(
    chart_config: dict[str, Any] | None,
    result: dict[str, Any] | None,
    patch: dict[str, Any] | None,
) -> tuple[dict[str, Any], str]:
    """Apply a structured chart patch from the LLM classifier.

    This function is the deterministic guardrail: every field is validated
    against the renderer's closed chart vocabulary and the columns that actually
    exist in the cached result, so the chart is always drawable and grounded.
    """
    if not chart_config:
        chart_config = {}
    if not result:
        result = {}
    if not patch:
        return dict(chart_config), "I couldn't understand that chart change."

    columns = list(result.get("columns") or [])
    new_config = dict(chart_config)
    applied: list[str] = []

    type_changed = patch.get("type") in _CHART_TYPES
    if type_changed:
        new_config["type"] = patch["type"]
        new_config.pop("subtype", None)
        applied.append("type")

    subtype = patch.get("subtype")
    if subtype and subtype in _CHART_SUBTYPES.get(new_config.get("type", ""), frozenset()):
        new_config["subtype"] = subtype
        applied.append("subtype")

    label = patch.get("labelColumn")
    if label:
        if label in columns:
            new_config["labelColumn"] = label
            applied.append("label")
        else:
            return chart_config, f"Column '{label}' is not in this result. Available columns: {', '.join(columns)}."

    value_columns = patch.get("valueColumns")
    if isinstance(value_columns, list):
        missing = [c for c in value_columns if c not in columns]
        if missing:
            return chart_config, f"Column(s) {', '.join(missing)} are not in this result. Available columns: {', '.join(columns)}."
        new_config["valueColumns"] = value_columns
        applied.append("values")

    sort = patch.get("sort")
    if isinstance(sort, dict):
        col = str(sort.get("column", ""))
        direction = str(sort.get("direction", "")).lower()
        if direction not in ("asc", "desc"):
            direction = "desc"
        if col and (col in columns or col in ("value", "label")):
            new_config["sort"] = {"column": col, "direction": direction}
            applied.append("sort")
        else:
            return chart_config, f"Sort column '{col}' is not in this result."

    if "dataLabels" in patch:
        new_config["dataLabels"] = bool(patch["dataLabels"])
        applied.append("data labels")

    if "legendVisible" in patch:
        new_config["legend"] = {"visible": bool(patch["legendVisible"])}
        applied.append("legend")

    if "title" in patch:
        title = str(patch["title"]).strip()
        if title:
            new_config["title"] = title
            applied.append("title")

    # Validate: pie/donut needs one value column and a label column.
    if new_config.get("type") == "pie":
        if not new_config.get("labelColumn") or len(new_config.get("valueColumns", [])) != 1:
            return chart_config, "A pie chart needs one category column and one numeric value."

    return new_config, _patch_message(applied, new_config)


def _build_explanation(
    sql: str | None,
    result: dict[str, Any] | None,
    chart_config: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "sql": sql,
        "rowCount": (result or {}).get("rowCount") if result else None,
        "columns": (result or {}).get("columns") if result else None,
        "chartType": (chart_config or {}).get("type"),
        "generatedAt": datetime.now(UTC).isoformat(),
    }


async def _run_analytical_turn(
    session: AsyncSession,
    context: RequestContext,
    project_id: int,
    question: str,
    prior_turn: AnalyticsConversationTurn | None,
    datasource_id: int | None,
) -> dict[str, Any]:
    """Run a data-changing turn by delegating to the existing ask-and-run core."""
    # When this is a follow-up and we have prior SQL, prepend a concise context
    # line to the question so the generator can refine instead of starting from
    # scratch. The AI query endpoint treats the prompt as the full user request.
    prompt = question
    if prior_turn and prior_turn.sql:
        prompt = (
            f"Previous query: {prior_turn.sql}\n"
            f"User follow-up: {question}\n"
            "Generate a single, safe replacement query incorporating the follow-up."
        )

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

    intent, chart_patch = await classify_turn(
        question,
        prior_turn,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        project_id=conversation.project_id,
    )
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
        new_config, message = apply_chart_patch(chart_config, result_cache, chart_patch)
        if "not in this result" in message or "needs one category" in message:
            turn.intent_type = ConversationalIntent.CLARIFICATION
            turn.status = "clarification"
            turn.assistant_message = message
            turn.chart_config = chart_config
            turn.result_cache = result_cache
            turn.sql = prior_turn.sql
            return

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

    run = await _run_analytical_turn(
        session,
        context,
        project_id,
        question,
        prior_turn,
        datasource_id,
    )

    turn.sql = run.get("sql") or None
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

    turn.result_cache = result_cache
    turn.result_metadata = profile
    turn.chart_config = chart_config
    turn.explanation = _build_explanation(turn.sql, result_cache, chart_config)
    turn.datasource_context = {"dataSourcesUsed": run.get("dataSourcesUsed", [])}
    turn.assistant_message = run.get("explanation") or "Here is the result."
    turn.status = "success"
