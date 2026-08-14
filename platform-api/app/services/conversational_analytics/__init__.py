
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.models.analytics_conversation import AnalyticsConversation, AnalyticsConversationTurn
from app.models.chat_attachment import ChatAttachment
from app.routes.ai_proxy import _ask_and_run_core, _forward_prose_answer
from app.services import ai_intelligence_client as ai_intelligence_client
from app.services.ai_governance import ai_governance_service, infer_governance_key
from app.services.ai_grounding import gather_grounding_evidence
from app.services.ai_intelligence_client import AIUnavailableError as AIUnavailableError
from app.services.business_insight_project_resolver import (
    resolve_business_insight_project,
)
from app.services.chat_attachment_adapter import build_attachment_context
from app.services.insight_card_match import (
    _extract_terms as _extract_insight_terms,
)
from app.services.insight_card_match import (
    find_matching_insight_cards,
)
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
from .intent_classification import _is_document_question as _is_document_question
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


def _live_query_score(
    question: str,
    result_cache: dict[str, Any],
    data_sources: list[str],
) -> float:
    """Score how directly a live result answers the question.

    Returns a 0-1 value based on term overlap between the question and the
    result columns, source names, and a few sample values. A high score means
    the live query already covers the user's topic; a low score means the
    result may be generic or off-topic, so a matched Insight Card can add
    grounded analysis.
    """
    q_terms = _extract_insight_terms(question)
    if not q_terms:
        return 0.0

    columns = result_cache.get("columns") or []
    rows = result_cache.get("rows") or []
    sample_values: list[str] = []
    for row in rows[:3]:
        for v in row.values():
            if isinstance(v, str | int | float):
                sample_values.append(str(v))

    haystack = " ".join(
        [str(c) for c in columns]
        + [str(s) for s in data_sources]
        + sample_values
    )
    h_terms = _extract_insight_terms(haystack)
    overlap = len(q_terms & h_terms)
    if not overlap:
        return 0.1 if rows else 0.0
    return min(1.0, overlap / len(q_terms))


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


def _data_result_for_synthesis(
    result_cache: dict[str, Any],
    chart_config: dict[str, Any],
    sql: str | None,
    data_sources_used: list[str],
) -> dict[str, Any]:
    """Shape the executed result into a block the AI server can synthesize."""
    data: dict[str, Any] = {
        "columns": result_cache.get("columns", []),
        "rows": result_cache.get("rows", []),
        "rowCount": result_cache.get("rowCount", 0),
        "truncated": result_cache.get("truncated", False),
        "sql": sql or "",
        "dataSourcesUsed": data_sources_used,
    }
    if chart_config:
        data["chart_config"] = chart_config
    return data


def _matched_insight_dict(m: Any) -> dict[str, Any]:
    """Serialize an InsightCardMatch (or related dict) for the AI server."""
    if isinstance(m, dict):
        return m
    return {
        "insightId": m.insight_id,
        "projectId": m.project_id,
        "projectName": m.project_name,
        "title": m.title,
        "summary": m.summary,
        "chart": m.chart,
        "severity": m.severity,
        "diagnostics": m.diagnostics,
        "proposedActions": m.proposed_actions,
        "score": m.score,
    }


async def _synthesize_answer(
    context: RequestContext,
    project_id: int,
    question: str,
    *,
    data_result: dict[str, Any] | None = None,
    matched_insights: list[dict[str, Any]] | None = None,
) -> str | None:
    """Ask the LLM to synthesize the final answer from data and/or insight cards.

    Returns ``None`` when the AI server is unavailable so callers can fall back
    to deterministic text.
    """
    try:
        response = await ai_intelligence_client.ask(
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            project_id=project_id,
            question=question,
            scope="project",
            data_result=data_result,
            matched_insights=matched_insights,
        )
        if response and response.get("answer"):
            return str(response["answer"]).strip()
    except AIUnavailableError:
        logger.warning("AI answer synthesis unavailable; using deterministic fallback")
    except Exception as exc:
        logger.warning("Answer synthesis failed: %s", exc)
    return None


async def execute_turn(
    session: AsyncSession,
    context: RequestContext,
    conversation: AnalyticsConversation,
    turn: AnalyticsConversationTurn,
    *,
    datasource_id: int | None = None,
    attachment_ids: list[int] | None = None,
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

    attachment_context = await build_attachment_context(
        session, context.tenant_id, attachment_ids or []
    )
    if attachment_ids:
        from sqlalchemy import update
        await session.execute(
            update(ChatAttachment)
            .where(
                ChatAttachment.id.in_(attachment_ids),
                ChatAttachment.tenant_id == context.tenant_id,
                ChatAttachment.conversation_id == conversation.id,
                ChatAttachment.deleted_at.is_(None),
            )
            .values(message_id=turn.id)
        )

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

    if attachment_context:
        # Inject authorized attachment context only into model prompts, not into
        # the persisted user message. This preserves the existing classifier and
        # grounding behavior for text-only turns.
        question = f"{attachment_context}\n\n{question}"
        sql_question = f"{attachment_context}\n\n{sql_question}"

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
    # Re-resolve the project every turn for cross-project surfaces (Business
    # Insight / AI Assistant) so a follow-up can switch projects and a question
    # like "Show me IT backup jobs" routes to the IT project even if the
    # conversation was previously pinned to Manufacturing. Project Insights is
    # page-scoped, so its project never changes mid-conversation.
    is_project_scoped = conversation.surface == "project_insights"
    project_id = conversation.project_id
    if not is_project_scoped:
        resolved = await resolve_business_insight_project(
            session, context, question
        )
        if resolved.status == "resolved" and resolved.project_id:
            project_id = resolved.project_id
            conversation.project_id = project_id

    if project_id is None:
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

    # Phase D: Reference Library / document Q&A bypasses SQL generation.
    # These questions are answered directly from grounded documents and KG context.
    if _is_document_question(question):
        grounding = await gather_grounding_evidence(
            session,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            project_id=project_id,
            question=question,
        )
        if grounding is None:
            from app.schemas.ai_grounding import GroundingEvidence
            grounding = GroundingEvidence()
        grounding_dict = grounding.model_dump()
        prose = await _forward_prose_answer(
            session,
            context,
            project_id=project_id,
            question=question,
            history=[],
            scope="project",
            include_query_history=False,
            include_dashboard_context=False,
            grounding_evidence=grounding_dict,
        )
        answer = (
            prose.get("answer") if isinstance(prose, dict) else (str(prose) if prose else "")
        )
        turn.assistant_message = (
            answer
            or "I couldn't find a relevant document for that question. Try rephrasing or checking the Reference Library."
        )
        turn.status = "success"
        turn.intent_type = ConversationalIntent.DOCUMENT_QA
        turn.result_metadata = {
            "documentQa": {
                "referenceDocumentCount": len(grounding.reference_documents),
                "kgNodeCount": len(grounding.kg_nodes),
            }
        }
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
        # may already be answered by one or more existing, verified Insight Cards —
        # that analysis ran the real multi-query pipeline, so pointing back to it
        # beats both a hard SQL error and unattributed KG prose. Check before
        # falling further back.
        card_matches = await find_matching_insight_cards(
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
            max_cards=3,
        )
        if card_matches:
            primary = card_matches[0]
            related = card_matches[1:]
            turn.chart_config = None
            turn.result_cache = None
            turn.sql = None
            turn.sql_fingerprint = None
            turn.datasource_context = {"dataSourcesUsed": []}
            matched_insights = [_matched_insight_dict(primary)] + [
                _matched_insight_dict(m) for m in related
            ]
            turn.matched_insight = {
                "insightId": primary.insight_id,
                "projectId": primary.project_id,
                "projectName": primary.project_name,
                "title": primary.title,
                "summary": primary.summary,
                "chart": primary.chart,
                "severity": primary.severity,
                "diagnostics": primary.diagnostics,
                "proposedActions": primary.proposed_actions,
                "score": primary.score,
                "relatedInsights": [
                    {
                        "insightId": m.insight_id,
                        "projectId": m.project_id,
                        "projectName": m.project_name,
                        "title": m.title,
                        "summary": m.summary,
                        "chart": m.chart,
                        "severity": m.severity,
                        "diagnostics": m.diagnostics,
                        "proposedActions": m.proposed_actions,
                        "score": m.score,
                    }
                    for m in related
                ],
            }
            # Keep the fallback message focused on the existing analysis the
            # user can act on. The live-query failure reason is still captured
            # in result_metadata for debugging, but it is not user-facing text.
            synthesized = await _synthesize_answer(
                context,
                project_id,
                question,
                matched_insights=matched_insights,
            )
            turn.assistant_message = (
                synthesized
                or f"I found an existing analysis that answers this: **{primary.title}**"
                + (f"\n\n{primary.summary}" if primary.summary else "")
            )
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
                "fallbackErrorDetails": run.get("errorDetails"),
                "insightCardScores": [m.score for m in card_matches],
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
        answer = prose.get("answer") if isinstance(prose, dict) else (str(prose) if prose else "")
        if answer:
            turn.assistant_message = answer
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
    turn.status = "success"

    # If the live result is on-topic but there is a strong, precomputed Insight
    # Card that adds deeper grounded analysis, return both. The Insight Card is
    # surfaced below the live chart so the user gets the fresh numbers plus the
    # existing diagnostics and proposed actions.
    matched_insights_for_synthesis: list[dict[str, Any]] | None = None
    live_score = _live_query_score(
        question, result_cache, run.get("dataSourcesUsed") or []
    )
    if live_score < 0.95:
        insight_matches = await find_matching_insight_cards(
            session,
            context=context,
            tenant_id=context.tenant_id,
            project_id=project_id,
            question=question,
            allow_cross_project=conversation.surface != "project_insights",
            max_cards=2,
            use_llm=False,
        )
        if insight_matches:
            primary = insight_matches[0]
            normalized_insight_score = min(1.0, (primary.score or 0.0) / 4.0)
            if normalized_insight_score >= 0.65 and normalized_insight_score > live_score:
                related = insight_matches[1:]
                turn.matched_insight = {
                    "insightId": primary.insight_id,
                    "projectId": primary.project_id,
                    "projectName": primary.project_name,
                    "title": primary.title,
                    "summary": primary.summary,
                    "chart": primary.chart,
                    "severity": primary.severity,
                    "diagnostics": primary.diagnostics,
                    "proposedActions": primary.proposed_actions,
                    "score": primary.score,
                    "relatedInsights": [
                        {
                            "insightId": m.insight_id,
                            "projectId": m.project_id,
                            "projectName": m.project_name,
                            "title": m.title,
                            "summary": m.summary,
                            "chart": m.chart,
                            "severity": m.severity,
                            "diagnostics": m.diagnostics,
                            "proposedActions": m.proposed_actions,
                            "score": m.score,
                        }
                        for m in related
                    ],
                }
                matched_insights_for_synthesis = [_matched_insight_dict(primary)] + [
                    _matched_insight_dict(m) for m in related
                ]

    data_result = _data_result_for_synthesis(
        result_cache, chart_config, turn.sql, run.get("dataSourcesUsed") or []
    )
    synthesized = await _synthesize_answer(
        context,
        project_id,
        question,
        data_result=data_result,
        matched_insights=matched_insights_for_synthesis,
    )
    turn.assistant_message = (
        synthesized
        or run.get("explanation")
        or _answer_text(columns, bounded_rows)
    )
