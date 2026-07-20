"""Conversational analytics orchestration.

Submits analytical turns, classifies intent LLM-first, delegates SQL
generation/execution to the existing ask-and-run core, applies chart-only
changes as validated structured patches, and persists the conversation state
so follow-ups can reuse prior successful results.

Intent and chart-format decisions are made by the AI server
(``/ai/intelligence/conversation-turn``) from the grounded conversation state
— nothing about the user's phrasing is hardcoded here. This module only
*validates* what the model returns (renderer-supported chart types, columns
that actually exist in the result) and provides a minimal degraded-mode
fallback for when the AI server is disabled or unreachable.
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
from app.routes.ai_proxy import _ask_and_run_core, _forward_prose_answer
from app.services import ai_intelligence_client
from app.services.ai_governance import ai_governance_service, infer_governance_key
from app.services.ai_intelligence_client import AIUnavailableError
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


# Closed chart vocabulary the web-ui WidgetRenderer supports. Used to VALIDATE
# chart patches (whether they come from the LLM or the degraded fallback) —
# never to decide intent.
_CHART_TYPES = {"table", "bar", "line", "pie", "scatter"}
_CHART_SUBTYPES: dict[str, set[str]] = {
    "bar": {
        "column",
        "horizontal_bar",
        "stacked_bar",
        "grouped_bar",
        "stacked_horizontal",
        "positive_negative",
        "waterfall",
    },
    "line": {"smooth_line", "step_line", "dashed_line", "stacked_area"},
    "pie": {"donut", "two_level", "gauge"},
    "scatter": {"bubble", "best_fit"},
    "table": set(),
}

# ---------------------------------------------------------------------------
# Degraded-mode fallback (AI server disabled or unreachable ONLY).
# Deliberately tiny: it recognizes an explicit chart-format mention or an
# explain request; everything else re-runs through the SQL engine.
# ---------------------------------------------------------------------------
_FALLBACK_CHART_WORDS: list[tuple[str, str, str | None]] = [
    ("horizontal bar", "bar", "horizontal_bar"),
    ("stacked bar", "bar", "stacked_bar"),
    ("grouped bar", "bar", "grouped_bar"),
    ("donut", "pie", "donut"),
    ("doughnut", "pie", "donut"),
    ("area", "line", "stacked_area"),
    ("bubble", "scatter", "bubble"),
    ("bar", "bar", None),
    ("column", "bar", None),
    ("line", "line", None),
    ("pie", "pie", None),
    ("scatter", "scatter", None),
    ("table", "table", None),
]
_FALLBACK_CHART_CONTEXT = re.compile(
    r"\b(chart|graph|plot|format|visuali[sz]e|visuali[sz]ation|show|display|"
    r"switch|change|make|turn|render|draw|convert|run)\b"
)
_FALLBACK_EXPLAIN = re.compile(
    r"\b(explain|why|how did you|how was this|show (?:me )?the sql|"
    r"view (?:the )?sql|what sql)\b"
)


def _normalize_question(question: str) -> str:
    return re.sub(r"\s+", " ", question.strip().lower())


def _prior_turn_state(prior_turn: AnalyticsConversationTurn | None) -> dict[str, Any]:
    """Grounded conversation state handed to the classifier."""
    if prior_turn is None or not prior_turn.result_cache:
        return {"has_prior_result": False}
    profile = prior_turn.result_metadata or {}
    cache = prior_turn.result_cache or {}
    return {
        "has_prior_result": True,
        "prior_sql": prior_turn.sql or "",
        "result_columns": cache.get("columns", []),
        "numeric_columns": profile.get("numericColumns", []),
        "categorical_columns": profile.get("categoricalColumns", []),
        "row_count": cache.get("rowCount", 0),
        "current_chart": prior_turn.chart_config or {},
    }


async def classify_turn(
    question: str,
    prior_turn: AnalyticsConversationTurn | None,
    *,
    tenant_id: int,
    user_id: int,
    project_id: int,
) -> tuple[str, dict[str, Any], str | None]:
    """Classify a turn LLM-first; degrade deterministically when AI is off.

    Returns the intent, the structured chart patch produced by the model
    (already sanitized server-side, re-validated in :func:`apply_chart_patch`),
    and an optional ``data_question`` to send to the SQL generator with chart
    language removed.
    """
    state = _prior_turn_state(prior_turn)
    if ai_intelligence_client.is_enabled():
        try:
            decision = await ai_intelligence_client.classify_conversation_turn(
                tenant_id=tenant_id,
                user_id=user_id,
                project_id=project_id,
                message=question,
                **state,
            )
        except AIUnavailableError as exc:
            logger.warning("Conversation-turn classifier unavailable: %s", exc)
            decision = None
        if decision:
            intent = decision.get("intent")
            if intent in {
                ConversationalIntent.NEW_ANALYSIS,
                ConversationalIntent.QUERY_CHANGE,
                ConversationalIntent.CHART_CHANGE,
                ConversationalIntent.EXPLAIN,
                ConversationalIntent.CLARIFICATION,
            }:
                if intent in {ConversationalIntent.CHART_CHANGE, ConversationalIntent.EXPLAIN} and not state[
                    "has_prior_result"
                ]:
                    intent = ConversationalIntent.NEW_ANALYSIS
                chart = decision.get("chart") or {}
                logger.info(
                    "Conversation turn classified intent=%s confidence=%s reason=%s",
                    intent,
                    decision.get("confidence"),
                    decision.get("reason"),
                )
                # New-analysis and query-change turns may also carry a chart
                # preference from the model (e.g. "Run X with a horizontal bar
                # chart"). Preserve it so execute_turn can apply it after SQL.
                # data_question is the user's data intent with chart language
                # removed, surfaced so the SQL generator is not confused by
                # presentation wording.
                data_question = decision.get("data_question")
                if data_question and not isinstance(data_question, str):
                    data_question = None
                return intent, chart, _grounded_data_question(question, data_question)
    return _fallback_classify(question, prior_turn)


# Generic analytics filler that appears in almost any rewritten data question;
# grounding requires overlap on words that actually carry the user's subject.
_DATA_QUESTION_FILLER = {
    "a", "an", "the", "of", "by", "for", "and", "or", "to", "in", "with",
    "count", "counts", "total", "totals", "number", "sum", "average", "avg",
    "grouped", "group", "per", "show", "list", "all", "each", "values",
    "labelled", "labeled", "breakdown", "distribution",
}


def _grounded_data_question(question: str, data_question: str | None) -> str | None:
    """Accept the model's rewritten data question only if it stays grounded
    in the user's actual message.

    Guards against the model parroting an example or a previous project's
    phrasing: the rewrite must share at least one non-filler content word with
    what the user typed, otherwise the raw question is used instead.
    """
    if not data_question or not data_question.strip():
        return None
    q_tokens = set(re.findall(r"[a-z0-9]+", question.lower()))
    dq_tokens = set(re.findall(r"[a-z0-9]+", data_question.lower()))
    content = dq_tokens - _DATA_QUESTION_FILLER
    if not content or not (content & q_tokens):
        logger.warning(
            "Discarding ungrounded data_question %r for message %r",
            data_question,
            question,
        )
        return None
    return data_question.strip()


def _fallback_classify(
    question: str, prior_turn: AnalyticsConversationTurn | None
) -> tuple[str, dict[str, Any], str | None]:
    """Minimal deterministic classifier for degraded mode (AI off/unreachable)."""
    q = _normalize_question(question)
    has_result = bool(prior_turn and prior_turn.result_cache)
    if has_result and _FALLBACK_EXPLAIN.search(q):
        return ConversationalIntent.EXPLAIN, {}, None
    if has_result and _FALLBACK_CHART_CONTEXT.search(q):
        for phrase, chart_type, subtype in _FALLBACK_CHART_WORDS:
            if re.search(rf"\b{phrase}\b", q):
                patch: dict[str, Any] = {"type": chart_type}
                if subtype:
                    patch["subtype"] = subtype
                return ConversationalIntent.CHART_CHANGE, patch, None
    if prior_turn is None:
        # Even a brand-new question can name a chart style ("Run X with a
        # horizontal bar chart"). Pass the preference along so the widget can
        # honor it after SQL generation.
        for phrase, chart_type, subtype in _FALLBACK_CHART_WORDS:
            if re.search(rf"\b{phrase}\b", q):
                initial_patch = {"type": chart_type}
                if subtype:
                    initial_patch["subtype"] = subtype
                return ConversationalIntent.NEW_ANALYSIS, initial_patch, None
        return ConversationalIntent.NEW_ANALYSIS, {}, None
    # Ambiguous follow-up: re-run through the SQL engine, the safe default.
    return ConversationalIntent.QUERY_CHANGE, {}, None

def _answer_text(columns: list[str], rows: list[dict[str, Any]]) -> str:
    """Short deterministic answer for an executed data turn.

    States the single scalar for KPI-style results, otherwise the row count.
    The chart + table carry the detail; raw model prose never reaches chat.
    """
    if not rows:
        return "The query ran but returned no rows."
    if len(rows) == 1 and len(columns) == 1:
        return f"{columns[0]}: {rows[0].get(columns[0])}"
    return f"Here are the results ({len(rows)} rows)."


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


def _to_float(value: Any) -> float | None:
    """Parse a scalar value to float, tolerating numeric strings."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        text = value.replace(",", "").strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _is_period_values(values: list[Any]) -> bool:
    """True when most non-null values look like sortable period labels."""
    non_null = [v for v in values if v is not None and v != ""]
    if not non_null:
        return False
    period_re = re.compile(r"^\s*(\d{4}|\d{4}[-/]\d{1,2}([-/]\d{1,2})?|q[1-4][\s-]?\d{2,4})\s*$", re.IGNORECASE)
    return sum(1 for v in non_null if period_re.match(str(v))) >= max(1, len(non_null) // 2)


def _column_data_profile(columns: list[str], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Classify each column as numeric, period, or categorical from its values."""
    profile: dict[str, Any] = {"numeric": [], "period": [], "categorical": []}
    for col in columns:
        values = [r.get(col) for r in rows]
        non_null = [v for v in values if v is not None and v != ""]
        if not non_null:
            profile["categorical"].append(col)
            continue
        numeric_count = sum(1 for v in non_null if _to_float(v) is not None)
        if numeric_count >= len(non_null) / 2:
            profile["numeric"].append(col)
        elif _is_period_values(non_null):
            profile["period"].append(col)
        else:
            profile["categorical"].append(col)
    return profile


def _pick_chart_fields(
    columns: list[str],
    rows: list[dict[str, Any]],
    chart_type: str,
    subtype: str | None = None,
) -> dict[str, Any]:
    """Choose grounded label/value/metric columns for a chart type."""
    profile = _column_data_profile(columns, rows)
    numeric = profile["numeric"]
    period = profile["period"]
    categorical = profile["categorical"]
    result: dict[str, Any] = {}

    if chart_type == "kpi":
        result["metricField"] = numeric[0] if numeric else (columns[-1] if columns else None)
        return result

    if chart_type in ("line", "area"):
        # Prefer a period axis, then a categorical axis, then the first column.
        label = period[0] if period else (categorical[0] if categorical else columns[0] if columns else None)
        value = numeric[0] if numeric else (columns[-1] if columns else None)
        if label:
            result["labelColumn"] = label
        if value:
            result["valueColumns"] = [value]
        return result

    if chart_type == "scatter":
        if len(numeric) >= 2:
            result["labelColumn"] = numeric[0]
            result["valueColumns"] = numeric[1:]
        elif numeric:
            result["valueColumns"] = [numeric[0]]
        return result

    # bar / pie and all other chart types need a categorical label + numeric value.
    # Prefer categorical labels, then period labels (which work as bar categories),
    # then fall back to the first column.
    label = categorical[0] if categorical else (period[0] if period else (columns[0] if columns else None))
    value = numeric[0] if numeric else (columns[-1] if columns else None)
    if label:
        result["labelColumn"] = label
    if value:
        result["valueColumns"] = [value]
    return result


def _build_chart_config(
    suggested: dict[str, Any] | None,
    columns: list[str],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Normalize the ask-and-run visualization suggestion into a stable chart config."""
    if not suggested:
        suggested = {}
    chart_type = suggested.get("type") or "table"
    config: dict[str, Any] = {
        "type": chart_type,
        "title": suggested.get("title", "Chart"),
    }
    if suggested.get("chartStyle"):
        config["subtype"] = suggested["chartStyle"]
    if suggested.get("topN") is not None:
        config["topN"] = suggested["topN"]

    # Prefer the engine's explicit x/y/metric mapping when it is grounded in the
    # actual result columns.
    x_field = suggested.get("xField")
    y_field = suggested.get("yField")
    metric_field = suggested.get("metricField") or y_field
    if x_field in columns:
        config["labelColumn"] = x_field
    if y_field in columns:
        config["valueColumns"] = [y_field]
    if metric_field in columns and chart_type == "kpi":
        config["metricField"] = metric_field

    # If the suggestion did not include usable fields, derive them from the data.
    if chart_type != "table" and "valueColumns" not in config and "metricField" not in config:
        derived = _pick_chart_fields(columns, rows, chart_type, config.get("subtype"))
        config.update(derived)

    return config


_SUBTYPE_LABELS = {
    "horizontal_bar": "horizontal bar",
    "stacked_bar": "stacked bar",
    "grouped_bar": "grouped bar",
    "stacked_horizontal": "stacked horizontal bar",
    "positive_negative": "diverging bar",
    "waterfall": "waterfall",
    "column": "column",
    "smooth_line": "smooth line",
    "step_line": "step line",
    "dashed_line": "dashed line",
    "stacked_area": "stacked area",
    "donut": "donut",
    "two_level": "two-level pie",
    "gauge": "gauge",
    "bubble": "bubble",
    "best_fit": "trend-line scatter",
}


def apply_chart_patch(
    chart_config: dict[str, Any],
    result: dict[str, Any],
    patch: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    """Apply a structured chart patch to the existing config.

    The patch comes from the LLM classifier (or the degraded fallback); this
    function is the deterministic guardrail: every field is validated against
    the renderer's chart vocabulary and the columns that actually exist in the
    cached result, so the chart is always drawable and always grounded.

    Returns the updated config and a short assistant message.
    """
    if not patch:
        return chart_config, (
            "I couldn't map that to a chart change. Try something like "
            "'show it as a horizontal bar chart' or 'change it to a donut'."
        )

    new_config = dict(chart_config)
    columns = (result.get("columns") or []) if result else []
    changes: list[str] = []

    type_changed = patch.get("type") in _CHART_TYPES
    if type_changed:
        new_config["type"] = patch["type"]
        # A new type resets any previous style unless the patch names one, so
        # "make it a vertical bar" clears horizontal_bar instead of keeping it.
        new_config.pop("subtype", None)
    subtype = patch.get("subtype")
    subtype_changed = bool(
        subtype and subtype in _CHART_SUBTYPES.get(new_config.get("type", ""), set())
    )
    if subtype_changed:
        new_config["subtype"] = subtype
    if type_changed or subtype_changed:
        style = _SUBTYPE_LABELS.get(new_config.get("subtype", ""), "")
        if new_config.get("type") == "table" and not style:
            changes.append("showing the result as a table")
        else:
            name = style or new_config.get("type", "")
            changes.append(f"changed the chart to a {name} chart")

    # Re-derive grounded label/value/metric columns whenever the chart type
    # changed or no drawable fields are present, but never overwrite an explicit
    # label/value choice from the patch.
    if new_config.get("type") not in ("table",) and columns:
        rows_for_fields = (result.get("rows") or []) if result else []
        derived = _pick_chart_fields(
            columns,
            rows_for_fields,
            new_config["type"],
            new_config.get("subtype"),
        )
        if "labelColumn" not in new_config and "metricField" not in new_config:
            new_config.setdefault("labelColumn", derived.get("labelColumn"))
        new_config.setdefault("valueColumns", derived.get("valueColumns"))
        new_config.setdefault("metricField", derived.get("metricField"))

    label = patch.get("labelColumn")
    if label:
        if label not in columns:
            return chart_config, (
                f"Column '{label}' is not in this result. "
                f"Available columns: {', '.join(columns) or 'none'}."
            )
        new_config["labelColumn"] = label
        changes.append(f"using {label} as the label")

    values = patch.get("valueColumns")
    if values:
        missing = [v for v in values if v not in columns]
        if missing:
            return chart_config, (
                f"Column '{missing[0]}' is not in this result. "
                f"Available columns: {', '.join(columns) or 'none'}."
            )
        new_config["valueColumns"] = list(values)
        changes.append(f"plotting {', '.join(values)}")

    if isinstance(patch.get("sort"), dict):
        sort = patch["sort"]
        if sort.get("column") and sort.get("direction") in ("asc", "desc"):
            new_config["sort"] = {"column": sort["column"], "direction": sort["direction"]}
            direction = "descending" if sort["direction"] == "desc" else "ascending"
            changes.append(f"sorted by {sort['column']} {direction}")

    if isinstance(patch.get("dataLabels"), bool):
        new_config["dataLabels"] = patch["dataLabels"]
        changes.append("data labels {}".format("on" if patch["dataLabels"] else "off"))

    if isinstance(patch.get("legendVisible"), bool):
        new_config["legend"] = {"visible": patch["legendVisible"]}
        changes.append("legend {}".format("on" if patch["legendVisible"] else "off"))

    if patch.get("title"):
        new_config["title"] = str(patch["title"])[:120]
        changes.append("renamed the chart")

    # Pie/donut needs one category and one numeric value; adapt rather than fail.
    if new_config.get("type") == "pie":
        if not new_config.get("labelColumn") and columns:
            non_numeric = [c for c in columns if c not in (new_config.get("valueColumns") or [])]
            if non_numeric:
                new_config["labelColumn"] = non_numeric[0]
        current_values = new_config.get("valueColumns") or []
        if len(current_values) > 1:
            new_config["valueColumns"] = current_values[:1]
        if not new_config.get("labelColumn") or not new_config.get("valueColumns"):
            return chart_config, "A pie chart needs one category column and one numeric value."

    if not changes:
        return chart_config, (
            "I couldn't map that to a chart change. Try something like "
            "'show it as a horizontal bar chart' or 'change it to a donut'."
        )
    message = "; ".join(changes)
    return new_config, message[0].upper() + message[1:] + "."


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

    intent, chart_patch, data_question = await classify_turn(
        question,
        prior_turn,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        project_id=conversation.project_id or 0,
    )
    # The classifier strips chart/presentation wording from the user message and
    # returns a focused data_question. Use it for SQL generation so the model
    # does not try to interpret "horizontal", "donut", etc. as data intent.
    sql_question = data_question if data_question else question
    turn.intent_type = intent

    if intent == ConversationalIntent.CLARIFICATION:
        turn.status = "error"
        turn.error_code = "needs_clarification"
        turn.assistant_message = (
            "I'm not sure what you'd like me to do. You can ask a new question, "
            "refine the current one, or ask for a different chart format."
        )
        return

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
        sql_question,
        prior_turn,
        datasource_id,
        project_context=project_context,
    )

    turn.sql = run.get("sql") or None
    turn.project_context_version = project_context.get("version") if project_context else None
    turn.sql_fingerprint = _sql_fingerprint(turn.sql)

    if run.get("status") == "generation_error":
        # A question that cannot be grounded on an authorized source may still
        # be a document/KG question; answer it with a prose fallback instead of
        # a hard SQL error. Degrades gracefully if the AI service is busy.
        prose = await _forward_prose_answer(
            session,
            context,
            project_id=project_id,
            question=question,
        )
        if prose:
            turn.assistant_message = prose
            turn.chart_config = None
            turn.result_cache = None
            turn.sql = None
            turn.sql_fingerprint = None
            turn.datasource_context = {"dataSourcesUsed": []}
            turn.status = "success"
            return

    if run.get("status") != "success":
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

    # New-analysis/query-change turns may include a chart preference from the
    # model (e.g. "Run IT backup jobs with a horizontal bar chart"). Apply it
    # deterministically after SQL execution so the initial widget honors the
    # user's requested format.
    initial_patch = chart_patch
    if initial_patch:
        patched_config, patch_message = apply_chart_patch(chart_config, result_cache, initial_patch)
        if not (
            patch_message.startswith("I couldn't")
            or "not in" in patch_message
            or "needs" in patch_message
        ):
            chart_config = patched_config

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
    turn.assistant_message = run.get("explanation") or _answer_text(columns, bounded_rows)
    turn.status = "success"
