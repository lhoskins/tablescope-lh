
from __future__ import annotations

import logging
import re
from typing import Any

from app.models.analytics_conversation import AnalyticsConversationTurn
from app.services import ai_intelligence_client
from app.services.ai_intelligence_client import AIUnavailableError

logger = logging.getLogger(__name__)

_MAX_PREVIEW_ROWS = 200
_MAX_PREVIEW_BYTES = 1024 * 1024


class ConversationalIntent(str):
    NEW_ANALYSIS = "new_analysis"
    QUERY_CHANGE = "query_change"
    CHART_CHANGE = "chart_change"
    CREATE_QUERY = "create_query"
    CREATE_DASHBOARD = "create_dashboard"
    EXPLAIN = "explain"
    CLARIFICATION = "clarification"
    DOCUMENT_QA = "document_qa"
    UNSUPPORTED = "unsupported"


# Document/reference-library question markers. These short-circuit the SQL
# generation path so the response is grounded in Reference Library docs/KG.
_DOCUMENT_KEYWORDS = {
    "reference library", "reference libraries",
    "document", "documents", "doc",
    "policy", "policies", "procedure", "procedures",
    "guideline", "guidelines", "guidance", "standard", "standards",
    "framework", "frameworks", "best practice", "best practices",
    "compliance", "regulatory", "regulation", "regulations",
    "nist", "iso", "soc2", "gdpr", "hipaa",
}
_DOCUMENT_LIST_PATTERNS = [
    re.compile(r"\b(?:list|show|give me|what are|which)\b.*\b(?:document|documents|doc|docs|policy|policies|procedure|procedures|guideline|guidelines|standard|standards)\b"),
    re.compile(r"\b(?:document|documents|doc|docs|policy|policies|procedure|procedures|guideline|guidelines|standard|standards)\b.*\b(?:about|for|on|related to|in|in the)\b"),
]
_DOCUMENT_DETAIL_PATTERNS = [
    re.compile(r"\b(?:tell me more about|what does|what is in|details? (?:for|about|on)|more about|describe|explain)\b.*\b(?:document|doc|policy|procedure|guideline|standard|framework)\b"),
    re.compile(r"\b(?:the|a)\s+(?:document|doc|policy|procedure|guideline|standard|framework)\s+(?:called|named|titled)\b"),
]


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


# Artifact commands are deliberately detected before the general analytical
# classifier.  Creating a durable query/dashboard is a materially different
# user intent from merely answering a question, and it must always end in an
# explicit confirmation step.  Keeping this small command grammar in the
# platform also makes the safety behaviour deterministic when the AI service
# is unavailable.
_ARTIFACT_COMMAND_PREFIX = (
    r"^\s*(?:(?:please|kindly)\s+)?"
    r"(?:(?:can|could|would|will)\s+you\s+|i\s+(?:want|need)\s+you\s+to\s+)?"
)
_CREATE_DASHBOARD = re.compile(
    _ARTIFACT_COMMAND_PREFIX
    + r"(?:create|build|generate|make|design|prepare)\s+(?:me\s+)?(?:a\s+|an\s+|new\s+)?dashboard\b",
    re.IGNORECASE,
)
_CREATE_QUERY = re.compile(
    _ARTIFACT_COMMAND_PREFIX
    + r"(?:create|build|generate|make|prepare)\s+(?:me\s+)?(?:a\s+|an\s+|new\s+)?(?:saved\s+)?query\b",
    re.IGNORECASE,
)
_SAVE_AS_DASHBOARD = re.compile(
    _ARTIFACT_COMMAND_PREFIX
    + r"(?:save|turn|add)\s+(?:this|that|the\s+(?:result|analysis|answer))\s+(?:as|into|to)\s+(?:a\s+|an\s+)?dashboard\b",
    re.IGNORECASE,
)
_SAVE_AS_QUERY = re.compile(
    _ARTIFACT_COMMAND_PREFIX
    + r"(?:save|turn)\s+(?:this|that|the\s+(?:result|analysis|answer|sql))\s+(?:as|into)\s+(?:a\s+|an\s+)?query\b",
    re.IGNORECASE,
)


def artifact_intent(question: str) -> str | None:
    """Return an explicit durable-artifact command, if present.

    Dashboard is checked first because dashboard requests commonly contain the
    word "query" when describing their supporting data.
    """
    if _CREATE_DASHBOARD.search(question) or _SAVE_AS_DASHBOARD.search(question):
        return ConversationalIntent.CREATE_DASHBOARD
    if _CREATE_QUERY.search(question) or _SAVE_AS_QUERY.search(question):
        return ConversationalIntent.CREATE_QUERY
    return None


def artifact_data_question(question: str) -> str:
    """Strip the leading create-query command before SQL generation."""
    cleaned = _CREATE_QUERY.sub("", question, count=1).strip(" :-")
    cleaned = re.sub(
        r"^(?:(?:that|which)\s+)?(?:shows?|showing|returns?|returning|lists?|listing)\s+",
        "",
        cleaned,
        flags=re.I,
    )
    cleaned = re.sub(r"^(?:for|of)\s+", "", cleaned, flags=re.I)
    return cleaned or question


def is_save_existing_query_request(question: str) -> bool:
    """True when the user explicitly refers to the preceding result."""
    return bool(_SAVE_AS_QUERY.search(question))


def _normalize_question(question: str) -> str:
    return re.sub(r"\s+", " ", question.strip().lower())


_INVESTIGATIVE_PATTERNS = [
    re.compile(r"^\s*why\b"),
    re.compile(r"\bwhy\s+(?:is|are|did|does|has|have|was|were)\b"),
    re.compile(r"\bwhat'?s?\s+(?:driving|causing)\b"),
    re.compile(r"\bwhat\s+is\s+(?:driving|causing)\b"),
    re.compile(r"\broot\s+cause\b"),
    re.compile(r"\bwhat\s+explains\b"),
    re.compile(r"\breason\s+(?:for|behind)\b"),
    re.compile(r"\b(?:driving|contributing)\s+factors?\b"),
]


def _is_investigative_question(question: str) -> bool:
    """True for a root-cause ("why") question that benefits from running
    several targeted follow-up queries instead of a single one.

    Deliberately a cheap keyword/pattern check, not an LLM call -- consistent
    with every other question-shape classifier in this module (chart intent,
    document intent) and keeps the common case (a plain factual question)
    from paying for a decision it does not need.
    """
    text = _normalize_question(question)
    return any(p.search(text) for p in _INVESTIGATIVE_PATTERNS)


def _is_document_question(question: str) -> bool:
    """True when the user is asking about Reference Library documents/policies.

    These questions should bypass SQL generation and be answered directly from
    the grounded Reference Library and KG context.
    """
    text = _normalize_question(question)
    if any(k in text for k in _DOCUMENT_KEYWORDS):
        return True
    if any(p.search(text) for p in _DOCUMENT_LIST_PATTERNS):
        return True
    if any(p.search(text) for p in _DOCUMENT_DETAIL_PATTERNS):
        return True
    return False


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
    conversation_id: int | None = None,
    turn_id: int | None = None,
) -> tuple[str, dict[str, Any], str | None]:
    """Classify an explicit artifact command, otherwise use the LLM first.

    Returns the intent, the structured chart patch produced by the model
    (already sanitized server-side, re-validated in :func:`apply_chart_patch`),
    and an optional ``data_question`` to send to the SQL generator with chart
    language removed.
    """
    explicit_artifact_intent = artifact_intent(question)
    if explicit_artifact_intent is not None:
        data_question = (
            artifact_data_question(question)
            if explicit_artifact_intent == ConversationalIntent.CREATE_QUERY
            else None
        )
        return explicit_artifact_intent, {}, data_question

    state = _prior_turn_state(prior_turn)
    if ai_intelligence_client.is_enabled():
        try:
            decision = await ai_intelligence_client.classify_conversation_turn(
                tenant_id=tenant_id,
                user_id=user_id,
                project_id=project_id,
                message=question,
                conversation_id=conversation_id,
                turn_id=turn_id,
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
                ConversationalIntent.CREATE_QUERY,
                ConversationalIntent.CREATE_DASHBOARD,
                ConversationalIntent.EXPLAIN,
                ConversationalIntent.CLARIFICATION,
            }:
                if intent in {ConversationalIntent.CHART_CHANGE, ConversationalIntent.EXPLAIN} and not state[
                    "has_prior_result"
                ]:
                    intent = ConversationalIntent.NEW_ANALYSIS
                chart = decision.get("chart") or {}
                logger.info(
                    "Conversation turn classified conversation=%s turn=%s "
                    "intent=%s confidence=%s reason=%s",
                    conversation_id,
                    turn_id,
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
