
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.models.analytics_conversation import AnalyticsConversation, AnalyticsConversationTurn
from app.routes.ai_proxy import _ask_and_run_core, _forward_prose_answer
from app.services import ai_intelligence_client as ai_intelligence_client
from app.services.ai_governance import ai_governance_service, infer_governance_key
from app.services.ai_intelligence_client import AIUnavailableError as AIUnavailableError
from app.services.business_insight_project_resolver import (
    resolve_business_insight_project,
)
from app.services.insight_card_match import find_matching_insight_card
from app.services.project_ai_context import build_project_ai_context

from .chart_field_selection import _SUBTYPE_LABELS as _SUBTYPE_LABELS
from .chart_field_selection import _build_chart_config, apply_chart_patch
from .chart_field_selection import _pick_chart_fields as _pick_chart_fields
from .intent_classification import _CHART_SUBTYPES as _CHART_SUBTYPES
from .intent_classification import _CHART_TYPES as _CHART_TYPES
from .intent_classification import _DATA_QUESTION_FILLER as _DATA_QUESTION_FILLER
from .intent_classification import _FALLBACK_CHART_CONTEXT as _FALLBACK_CHART_CONTEXT
from .intent_classification import _FALLBACK_CHART_WORDS as _FALLBACK_CHART_WORDS
from .intent_classification import _FALLBACK_EXPLAIN as _FALLBACK_EXPLAIN
from .intent_classification import _MAX_PREVIEW_BYTES as _MAX_PREVIEW_BYTES
from .intent_classification import _MAX_PREVIEW_ROWS, ConversationalIntent, classify_turn, logger
from .intent_classification import _fallback_classify as _fallback_classify
from .intent_classification import _grounded_data_question as _grounded_data_question
from .intent_classification import _normalize_question as _normalize_question
from .intent_classification import _prior_turn_state as _prior_turn_state
from .result_profiling import _answer_text, _bound_result, _profile_result, _sql_fingerprint
from .result_profiling import _column_data_profile as _column_data_profile
from .result_profiling import _is_period_values as _is_period_values
from .result_profiling import _to_float as _to_float

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

    # A clarification intent from the classifier is an ambiguous phrasing, not a
    # reason to give up. Treat it like a new analysis so the SQL path gets a
    # chance to answer; the ask-and-run core falls back to a prose/KG answer if
    # it cannot ground the question on a data source.
    if intent == ConversationalIntent.CLARIFICATION:
        intent = ConversationalIntent.NEW_ANALYSIS
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
        # Business Insight and similar flows may have created the conversation
        # before project resolution existed; resolve from the question now.
        resolved = await resolve_business_insight_project(
            session, context, question
        )
        if resolved.status == "resolved" and resolved.project_id:
            project_id = resolved.project_id
            conversation.project_id = project_id
        else:
            turn.status = "error"
            turn.error_code = "no_project"
            turn.assistant_message = (
                "I couldn't tell which project this question belongs to. "
                "Please ask from a project page or mention a project name."
            )
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

    if run.get("status") in ("generation_error", "execution_error"):
        # A question that cannot be grounded or executed on an authorized source
        # may already be answered by an existing, verified Insight Card — that
        # analysis ran the real multi-query pipeline, so pointing back to it
        # beats both a hard SQL error and unattributed KG prose. Check before
        # falling further back.
        card_match = await find_matching_insight_card(
            session,
            context=context,
            tenant_id=context.tenant_id,
            project_id=project_id,
            question=question,
            # Project Insights is scoped to the project the user is already
            # looking at — widening there would answer from a different
            # project than the page the question was asked on. AI Assistant
            # and Business Insights have no such single-project framing, so
            # a card from any project the user can access is fair game.
            allow_cross_project=conversation.surface != "project_insights",
        )
        if card_match is not None:
            # State plainly that a fresh live query failed, and why, so a
            # real regression on a question that should trivially succeed
            # (a plain "show me X by Y" lookup) never hides behind a
            # good-looking card citation. But do not phrase it so the failure
            # reads as "I couldn't find an answer" — a card WAS found and
            # does answer the question; that has to be the sentence's actual
            # subject, with the live-query failure stated as its own fact
            # alongside it rather than swallowing it.
            reason = (
                "I couldn't build a live query for this question"
                if run.get("status") == "generation_error"
                else "I couldn't run a live query against your data just now"
            )
            # _ai_generation_error()'s "friendly" message defaults to a
            # generic string ("We could not safely build a query for this
            # question.") in exactly the cases that most need a real reason
            # -- e.g. the AI server being unreachable -- because the actual
            # detail only lands in errorDetails.validationError, which
            # nothing surfaces anywhere visible. Include it (still no raw
            # stack traces or dict reprs reach here -- both fields are
            # already sanitized by _ai_generation_error before this point).
            error_details = run.get("errorDetails")
            validation_error = (
                error_details.get("validationError")
                if isinstance(error_details, dict)
                else None
            )
            # Dedupe in case the friendly message and the validation detail
            # happen to be identical (e.g. a plain string HTTPException
            # detail with no dict wrapper flows into both) -- dict.fromkeys
            # dedupes while preserving order, unlike a set.
            detail_bits = list(dict.fromkeys(
                d for d in (run.get("error"), validation_error) if d
            ))
            detail_suffix = f" ({'; '.join(detail_bits)})" if detail_bits else ""
            turn.assistant_message = (
                f"{reason}{detail_suffix}. I found an existing analysis "
                f"that answers this: **{card_match.title}**"
            )
            if card_match.summary:
                turn.assistant_message += f"\n\n{card_match.summary}"
            turn.chart_config = None
            turn.result_cache = None
            turn.sql = None
            turn.sql_fingerprint = None
            turn.datasource_context = {"dataSourcesUsed": []}
            turn.matched_insight = {
                "insightId": card_match.insight_id,
                "projectId": card_match.project_id,
                "projectName": card_match.project_name,
                "title": card_match.title,
                "summary": card_match.summary,
                "chart": card_match.chart,
                "severity": card_match.severity,
                "diagnostics": card_match.diagnostics,
                "proposedActions": card_match.proposed_actions,
            }
            # Machine-readable trail for debugging why the live path failed,
            # even though the turn itself completed successfully from the
            # user's point of view. error_code is intentionally set despite
            # status="success" -- nothing in the schema or frontend treats a
            # non-null error_code as implying failure, and it is the only
            # place this reason is queryable/filterable server-side.
            turn.error_code = f"live_query_fallback_{run.get('status')}"
            turn.result_metadata = {
                "fallbackReason": run.get("status"),
                "fallbackError": run.get("error"),
                "fallbackErrorDetails": error_details,
            }
            turn.status = "success"
            return

        # No existing card answers it either; the question may still be
        # answerable from documents/KG prose instead of a hard SQL error.
        # Degrades gracefully if the AI service is busy.
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
