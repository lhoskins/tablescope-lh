"""Conversational turn classification."""

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter

from app.core.activity import update_activity
from app.core.config import settings
from app.core.security import verify_signature
from app.models.schemas import (
    ConversationTurnClassifyRequest,
    ConversationTurnClassifyResponse,
)
from app.services import llm_client
from app.services.prompt_loader import load_prompt_reference

from .ai_shared import _parse_json_response

logger = logging.getLogger(__name__)
router = APIRouter()


_CONVERSATION_INTENTS = {
    "new_analysis",
    "query_change",
    "chart_change",
    "explain",
    "clarification",
}

# Closed chart vocabulary — mirrors what the web-ui WidgetRenderer can draw.
# This grounds the model's output; it does NOT decide intent.
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

_CONVERSATION_TURN_SYSTEM_PROMPT = (
    "You are the routing brain of Tablescope's conversational analytics "
    "assistant. Your ONLY job is to classify the user's latest message and, "
    "when it is a presentation-only change, translate it into a structured "
    "chart patch. You never write SQL, never invent data, and never invent "
    "column names — you may only reference columns that appear in the result "
    "columns provided. Respond with a single JSON object and nothing else."
)


def _conversation_turn_prompt(req: ConversationTurnClassifyRequest) -> str:
    """Build the classification prompt: grounded state, shared best-practice
    rules + examples (from the editable prompt reference), the closed chart
    vocabulary generated from the renderer sets, and the output schema."""
    chart_json = json.dumps(req.current_chart or {}, default=str)
    subtype_lines = "\n".join(
        f'- "{t}": subtypes {sorted(subs) if subs else "[]"}'
        for t, subs in _CHART_SUBTYPES.items()
    )
    best_practices = load_prompt_reference(
        "conversational_analytics_best_practices.md"
    )
    return (
        "## Conversation state\n"
        f"- has_prior_result: {req.has_prior_result}\n"
        f"- prior_sql: {req.prior_sql or '(none)'}\n"
        f"- result_columns: {req.result_columns}\n"
        f"- numeric_columns: {req.numeric_columns}\n"
        f"- categorical_columns: {req.categorical_columns}\n"
        f"- row_count: {req.row_count}\n"
        f"- current_chart: {chart_json}\n\n"
        f"{best_practices}\n\n"
        "## Chart vocabulary (closed set)\n"
        f"Types: {sorted(_CHART_TYPES)}\n"
        f"{subtype_lines}\n\n"
        "## Output schema (JSON only, all keys required)\n"
        "{\n"
        '  "intent": "new_analysis|query_change|chart_change|explain|clarification",\n'
        '  "chart": {\n'
        '    "type": "table|bar|line|pie|scatter|null",\n'
        '    "subtype": "one of the listed subtypes or null",\n'
        '    "labelColumn": "column name or null",\n'
        '    "valueColumns": ["column names"] or null,\n'
        '    "sort": {"column": "label|value", "direction": "asc|desc"} or null,\n'
        '    "dataLabels": true/false/null,\n'
        '    "legendVisible": true/false/null,\n'
        '    "title": "new chart title or null"\n'
        "  },\n"
        '  "data_question": "underlying data question or null",\n'
        '  "confidence": 0.0-1.0,\n'
        '  "reason": "one short sentence"\n'
        "}\n\n"
        "## User message\n"
        f"{req.message}\n"
    )



def _sanitize_chart_patch(
    raw: Any, result_columns: list[str]
) -> dict[str, Any]:
    """Deterministic guardrail: keep only known keys and legal values.

    The model proposes; this validates. Unknown chart types/subtypes are
    dropped rather than guessed so the platform never receives a config the
    renderer cannot draw. Column references are passed through even when they
    don't exist — the platform surfaces a helpful message for those.
    """
    if not isinstance(raw, dict):
        return {}
    patch: dict[str, Any] = {}

    chart_type = raw.get("type")
    if isinstance(chart_type, str) and chart_type.lower() in _CHART_TYPES:
        patch["type"] = chart_type.lower()

    subtype = raw.get("subtype")
    if isinstance(subtype, str) and subtype:
        subtype = subtype.lower()
        allowed_for = _CHART_SUBTYPES.get(patch.get("type", ""), set())
        if not patch.get("type"):
            allowed_for = set().union(*_CHART_SUBTYPES.values())
        if subtype in allowed_for:
            patch["subtype"] = subtype

    # For new_analysis / query_change there is no prior result, so the model
    # cannot know the real column names yet. Ignore any guessed label/value
    # columns and let the platform derive them from the executed result. For
    # chart_change, result_columns is the prior result, so we preserve explicit
    # (even wrong) column requests so the platform can surface a clear error.
    if result_columns:
        label = raw.get("labelColumn")
        if isinstance(label, str) and label.strip():
            patch["labelColumn"] = label.strip()

        values = raw.get("valueColumns")
        if isinstance(values, list):
            cleaned = [v.strip() for v in values if isinstance(v, str) and v.strip()]
            if cleaned:
                patch["valueColumns"] = cleaned

    sort = raw.get("sort")
    if (
        isinstance(sort, dict)
        and sort.get("column") in ({"label", "value"} | set(result_columns))
        and sort.get("direction") in {"asc", "desc"}
    ):
        patch["sort"] = {"column": sort["column"], "direction": sort["direction"]}

    for key in ("dataLabels", "legendVisible"):
        if isinstance(raw.get(key), bool):
            patch[key] = raw[key]

    title = raw.get("title")
    if isinstance(title, str) and title.strip():
        patch["title"] = title.strip()[:120]

    return patch


@router.post(
    "/intelligence/conversation-turn",
    response_model=ConversationTurnClassifyResponse,
)
async def classify_conversation_turn(
    req: ConversationTurnClassifyRequest,
) -> ConversationTurnClassifyResponse:
    """Classify a conversational-analytics turn and emit a chart patch.

    LLM-first replacement for the platform's old regex intent tables: the
    model sees the grounded conversation state (real columns, current chart)
    and a closed chart vocabulary, and returns strict JSON. Deterministic
    validation afterwards guarantees the platform only ever receives legal
    intents and renderer-supported chart configs.
    """
    request_id = str(uuid.uuid4())
    verify_signature(req.model_dump(exclude={"signature"}, exclude_unset=True), req.signature)
    update_activity()

    raw = await llm_client.generate(
        prompt=_conversation_turn_prompt(req),
        system_prompt=_CONVERSATION_TURN_SYSTEM_PROMPT,
        model=req.model or settings.reasoning_model,
        temperature=0.0,
        max_tokens=400,
        num_ctx=8192,
        response_format="json",
        ollama_url=req.ollama_url,
    )
    parsed = _parse_json_response(raw or "") or {}

    intent = str(parsed.get("intent") or "").strip().lower()
    if intent not in _CONVERSATION_INTENTS:
        intent = "query_change" if req.has_prior_result else "new_analysis"
    # chart_change/explain require a prior result to act on.
    if intent in {"chart_change", "explain"} and not req.has_prior_result:
        intent = "new_analysis"

    # The model may also attach a chart preference to new_analysis or
    # query_change turns (e.g. "Run X with a horizontal bar chart"), so we
    # always sanitize and return the chart patch. For chart_change, an empty
    # patch means the model could not act on a presentation-only request.
    chart = _sanitize_chart_patch(parsed.get("chart"), req.result_columns)
    if intent == "chart_change" and not chart:
        # The model said "presentation change" but produced nothing actionable.
        intent = "clarification"

    try:
        confidence = min(max(float(parsed.get("confidence", 0.0)), 0.0), 1.0)
    except (TypeError, ValueError):
        confidence = 0.0

    data_question = str(parsed.get("data_question") or "").strip() or None
    if data_question and intent in {"chart_change", "explain"}:
        data_question = None

    logger.info(
        "Conversation turn classified | tenant=%d project=%d conversation=%s "
        "turn=%s | intent=%s confidence=%.2f",
        req.tenant_id, req.project_id, req.conversation_id, req.turn_id,
        intent, confidence,
    )

    return ConversationTurnClassifyResponse(
        intent=intent,
        chart=chart,
        data_question=data_question,
        confidence=confidence,
        reason=str(parsed.get("reason") or "")[:300],
        request_id=request_id,
        model_used=req.model or settings.reasoning_model,
    )
