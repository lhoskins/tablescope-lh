
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, has_role
from app.models.analytics_conversation import AnalyticsConversation, AnalyticsConversationTurn
from app.models.chat_attachment import ChatAttachment
from app.routes.ai_proxy import _ask_and_run_core, _build_source_catalog, _forward_prose_answer
from app.routes.ai_proxy_dashboard_designer import (
    DashboardDesignRequest,
    review_dashboard_design,
)
from app.services import ai_intelligence_client as ai_intelligence_client
from app.services.ai_governance import ai_governance_service, infer_governance_key
from app.services.ai_grounding import gather_grounding_evidence
from app.services.ai_intelligence_client import AIUnavailableError as AIUnavailableError
from app.services.business_insight_project_resolver import (
    resolve_business_insight_project,
)
from app.services.chat_attachment_adapter import (
    AttachmentAuthorizationError,
    build_attachment_context,
)
from app.services.insight_card_match import (
    _extract_terms as _extract_insight_terms,
)
from app.services.insight_card_match import (
    find_matching_insight_cards,
)
from app.services.project_ai_context import build_project_ai_context
from app.services.workspace_context import ActiveResourceContext, list_project_resource_candidates

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
from .intent_classification import (
    _MAX_PREVIEW_ROWS,
    ConversationalIntent,
    classify_turn,
    is_save_existing_query_request,
    logger,
)
from .intent_classification import _fallback_classify as _fallback_classify
from .intent_classification import _grounded_data_question as _grounded_data_question
from .intent_classification import _is_document_question as _is_document_question
from .intent_classification import _is_investigative_question as _is_investigative_question
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

Analytical and chart-format decisions are made by the AI server
(``/ai/intelligence/conversation-turn``) from the grounded conversation state.
Explicit durable-artifact commands are recognized by a small deterministic
grammar so query/dashboard creation always reaches a confirmation gate, even
when the AI server is disabled. The platform validates everything the model
returns and provides a minimal degraded-mode fallback for outages.
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


def _artifact_title(kind: str, prompt: str) -> str:
    """Create a concise editable name for a proposed chat artifact."""
    noun = "dashboard" if kind == "dashboard" else "query"
    cleaned = re.sub(
        rf"^\s*(?:(?:please|kindly)\s+)?"
        rf"(?:(?:can|could|would|will)\s+you\s+|i\s+(?:want|need)\s+you\s+to\s+)?"
        rf"(?:create|build|generate|make|design|prepare)\s+(?:me\s+)?"
        rf"(?:a\s+|an\s+|new\s+)?(?:saved\s+)?{noun}\b\s*",
        "",
        prompt,
        count=1,
        flags=re.IGNORECASE,
    ).strip(" :-?.")
    cleaned = re.sub(
        r"^(?:(?:that|which)\s+)?(?:shows?|showing|returns?|returning|lists?|listing)\s+",
        "",
        cleaned,
        flags=re.I,
    )
    cleaned = re.sub(r"^(?:for|of)\s+", "", cleaned, flags=re.I)
    if not cleaned or re.match(r"^(?:this|that|the\s+(?:result|analysis|answer|sql))\b", cleaned, re.I):
        return "AI Dashboard" if kind == "dashboard" else "AI Query"
    title = cleaned[0].upper() + cleaned[1:]
    return title[:120]


def _artifact_proposal(
    kind: str,
    prompt: str,
    *,
    sql: str | None = None,
    data_sources: list[str] | None = None,
    title: str | None = None,
    description: str | None = None,
    dashboard_design: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the persisted, non-destructive proposal rendered by Chats.

    ``dashboard_design`` carries everything needed to render an inline
    widget preview and, on accept, apply the design without reopening the
    guided designer: the raw AI ``suggestion`` (verbatim, ready for
    ``apply_dashboard_design``), a lightweight ``widgets`` summary for
    display, ``supportStatus``/``primaryDimensionCandidates``, and the
    generation parameters (``audience``/``emphasis``/``period``/``currency``/
    ``dimensionLabel``) apply must reuse for the result to match the preview.
    """
    return {
        "kind": kind,
        "status": "pending",
        "title": title or _artifact_title(kind, prompt),
        "prompt": prompt,
        "description": description or (
            "Validated against the project data shown above. Saving creates a governed project query."
            if kind == "query"
            else "Tablescope will profile project data and show the complete dashboard design before creation."
        ),
        "sql": sql if kind == "query" else None,
        "dataSources": data_sources or [],
        "dashboardDesign": dashboard_design,
        "createdAt": datetime.now(UTC).isoformat(),
        "assetId": None,
        "assetUrl": None,
    }


def _dashboard_widget_summaries(suggestion: dict[str, Any] | None) -> list[dict[str, Any]]:
    """A display-only summary of a dashboard suggestion's charts."""
    if not suggestion:
        return []
    summaries = []
    for widget in suggestion.get("widgets") or []:
        if not isinstance(widget, dict):
            continue
        summaries.append(
            {
                "title": str(widget.get("title") or "Untitled chart"),
                "chartType": str(widget.get("chartType") or "chart"),
                "businessQuestion": str(widget.get("businessQuestion") or ""),
            }
        )
    return summaries


async def _propose_dashboard(
    session: AsyncSession,
    context: RequestContext,
    turn: AnalyticsConversationTurn,
    *,
    project_id: int,
    prompt: str,
    governance: dict[str, Any],
) -> None:
    """Generate a best-practice dashboard design for ``prompt`` and attach it
    to ``turn`` as a pending artifact proposal -- no modal, no separate
    review step. The chat turn itself carries the same profiling/validation
    the guided designer's review screen does; accepting it applies the
    design directly (see ``decide_artifact_proposal``).
    """
    if not has_role(context.role, Role.EDITOR):
        turn.status = "error"
        turn.error_code = "forbidden"
        turn.assistant_message = "You need editor access on this project to create a dashboard."
        return

    generation_params = {
        "audience": "operational",
        "emphasis": "balanced_operational_health",
        "period": "1_year",
        "currency": "USD",
        "dimensionLabel": "Site",
    }
    try:
        review = await review_dashboard_design(
            DashboardDesignRequest(
                project_id=project_id,
                prompt=prompt,
                mode="create",
                audience=generation_params["audience"],
                emphasis=generation_params["emphasis"],
                period=generation_params["period"],
                currency=generation_params["currency"],
                dimension_label=generation_params["dimensionLabel"],
            ),
            session=session,
            context=context,
        )
    except AIUnavailableError:
        turn.status = "error"
        turn.error_code = "ai_unavailable"
        turn.assistant_message = "The AI service is currently unavailable. Please try again shortly."
        return
    except Exception:
        logger.exception("Dashboard design generation failed for project %s", project_id)
        turn.status = "error"
        turn.error_code = "dashboard_design_failed"
        turn.assistant_message = "I couldn't put together a dashboard design just now. Please try again."
        return

    support_status = review.get("supportStatus", "not_supported")
    turn.result_metadata = {"artifactKind": "dashboard", "supportStatus": support_status}
    turn.status = "success"

    if support_status == "not_supported" or not review.get("suggestion"):
        missing = review.get("missingRequirements") or []
        turn.explanation = {"generatedAt": datetime.now(UTC).isoformat(), "governance": governance}
        turn.assistant_message = (
            "I couldn't find enough validated data for that dashboard. "
            + (
                "Missing: " + "; ".join(missing) + "."
                if missing
                else "Try describing the metrics or records it should cover, or add a matching datasource."
            )
        )
        return

    suggestion = review["suggestion"]
    widgets = _dashboard_widget_summaries(suggestion)
    proposal = _artifact_proposal(
        "dashboard",
        prompt,
        title=str(suggestion.get("title") or _artifact_title("dashboard", prompt)),
        description=review.get("supportSummary"),
        data_sources=[s.get("viewName", "") for s in review.get("sources") or [] if s.get("viewName")],
        dashboard_design={
            "suggestion": suggestion,
            "widgets": widgets,
            "supportStatus": support_status,
            "primaryDimensionCandidates": review.get("primaryDimensionCandidates") or [],
            **generation_params,
        },
    )
    turn.explanation = {
        "generatedAt": datetime.now(UTC).isoformat(),
        "governance": governance,
        "artifactProposal": proposal,
    }
    chart_list = "; ".join(f"{w['title']} ({w['chartType']})" for w in widgets) or "a set of charts"
    caveat = (
        " Some requested data isn't fully available yet -- see the notes below."
        if support_status == "partially_supported"
        else ""
    )
    turn.assistant_message = (
        f"I put together a dashboard with {chart_list}, grounded in this project's data.{caveat} "
        "Click Create if it looks right, or tell me what to add, remove, or change."
    )


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


def _format_active_resource_prompt(
    active_resources: list[ActiveResourceContext] | None,
    focused_resource: ActiveResourceContext | None = None,
) -> str:
    """Return a short grounding block for the workspace's active items.

    A named workspace pins several cards at once, so every resolved card is
    listed. The assistant keeps full project access; this only narrows its
    default focus.

    ``focused_resource`` is the one the user is actually reading -- a document
    open in the workspace's preview pane, say. Without it the model gets the
    whole set as undifferentiated peers, so a question like "what should I fix
    first?" is as likely to be answered about a table the user isn't looking
    at. Naming the focus keeps the rest of the workspace available for
    cross-referencing while pointing the default interpretation at the item in
    front of them."""
    if not active_resources:
        return ""
    if len(active_resources) == 1:
        body = (
            f"The user currently has {active_resources[0].summary} "
            "open in this project workspace.\n"
        )
    else:
        lines = "\n".join(f"- {r.summary}" for r in active_resources)
        body = (
            "The user currently has these items open in this project workspace:\n"
            f"{lines}\n"
        )
    if focused_resource is not None and len(active_resources) > 1:
        # Descriptive, not imperative. An earlier version added "Answer about
        # that item unless the question says otherwise" -- and because this
        # block is prepended to the question the classifier sees, those
        # instructions changed the detected intent and routed turns away from
        # the SQL path entirely. State the fact and let the model weigh it, the
        # way the rest of this block does.
        body += f"Of those, the user is currently looking at {focused_resource.label}.\n"
    return f"--- Active workspace items ---\n{body}--- End active workspace items ---"


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
    conversation_id: int | None = None,
    turn_id: int | None = None,
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
        conversation_id=conversation_id,
        turn_id=turn_id,
    )
    return run


# Sub-questions run per investigation. Each is a full ask-and-run cycle (SQL
# generation, execution, self-repair), so this bounds latency/cost the same
# way _MAX_EXECUTE_ATTEMPTS/_MAX_REPAIR_STEPS bound the SQL repair agent.
_MAX_INVESTIGATION_STEPS = 3


def _investigation_step_summary(sub_question: str, run: dict[str, Any]) -> dict[str, Any]:
    """Bounded summary of one sub-query for the next planning decision and,
    later, for final-answer synthesis -- sample rows only, never the full
    result set, so the investigation prompt stays scoped as steps accumulate."""
    if run.get("status") != "success":
        return {
            "sub_question": sub_question,
            "sql": run.get("sql") or "",
            "columns": [],
            "row_count": 0,
            "sample_rows": [],
            "error": run.get("error") or "This sub-question could not be answered.",
        }
    rows = run.get("rows") or []
    return {
        "sub_question": sub_question,
        "sql": run.get("sql") or "",
        "columns": run.get("columns") or [],
        "row_count": len(rows),
        "sample_rows": rows[:5],
        "error": "",
    }


async def _run_investigation(
    session: AsyncSession,
    context: RequestContext,
    project_id: int,
    question: str,
    datasource_id: int | None,
    *,
    project_context: dict[str, Any] | None,
    conversation_id: int | None,
    turn_id: int | None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Multi-step "why" investigation: run up to ``_MAX_INVESTIGATION_STEPS``
    targeted sub-questions -- each through the existing ask-and-run core, so
    all SQL generation/execution/self-repair/governance is unchanged -- then
    return the last successful run plus the full step trace for synthesis.

    Every sub-question is planned by ``ai.investigate_step`` (see
    ``ai_intelligence_investigate_step.py``), which never writes or sees SQL
    itself, only the bounded summary of what each prior step found. Each
    sub-question runs as a fresh, standalone analytical question (not chained
    as a conversational follow-up) since these are exploratory branches off
    the ONE original question, not a continued conversation.

    Returns ``(last_successful_run_or_none, steps)``. The caller falls back
    to a normal single-query run when no step succeeds, so an
    investigative-sounding question is never worse off than the standard
    path -- this only adds capability, never removes the existing one.
    """
    steps: list[dict[str, Any]] = []
    last_successful_run: dict[str, Any] | None = None

    # Built once, reused for every planning step: the same catalog (with each
    # source's row count / date range / categorical values) that grounds SQL
    # generation, so the planner proposes sub-questions about columns that
    # actually exist and knows when the data can't support a "trend" at all,
    # instead of only ever seeing the original question and prior step
    # summaries. Best-effort -- an empty catalog degrades to today's behavior,
    # never blocks the investigation.
    try:
        source_catalog = await _build_source_catalog(session, context, project_id=project_id)
    except Exception as exc:
        logger.warning("Could not build source catalog for investigation planner: %s", exc)
        source_catalog = []

    for step_num in range(_MAX_INVESTIGATION_STEPS):
        steps_remaining = _MAX_INVESTIGATION_STEPS - step_num
        try:
            decision = await ai_intelligence_client.investigate_step(
                tenant_id=context.tenant_id,
                user_id=context.user_id,
                project_id=project_id,
                question=question,
                steps=steps,
                steps_remaining=steps_remaining,
                source_catalog=source_catalog,
            )
        except AIUnavailableError:
            decision = None

        if decision is None or decision["action"] != "query" or not decision.get("sub_question"):
            break

        sub_question = decision["sub_question"]
        run = await _run_analytical_turn(
            session,
            context,
            project_id,
            sub_question,
            None,  # each sub-question is a fresh, standalone question
            datasource_id,
            project_context=project_context,
            conversation_id=conversation_id,
            turn_id=turn_id,
        )
        steps.append(_investigation_step_summary(sub_question, run))
        if run.get("status") == "success":
            last_successful_run = run

    return last_successful_run, steps


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


_SNIPPET_TOTAL_CHARS = 6000
"""Combined ceiling for pinned excerpts, on top of history and grounding."""


def _format_context_snippets(snippets: list[tuple[str, str]] | None) -> str:
    """Quote the passages the user pinned to this conversation.

    Distinct from the active-resource block: that says which items are open,
    this carries the specific text someone judged worth keeping -- a paragraph
    of a report, or an insight from an earlier answer.

    Descriptive, never imperative, for the same reason as the resource block:
    this is prepended to the text the intent classifier reads, so instructions
    here would change how the turn is routed.
    """
    if not snippets:
        return ""
    lines: list[str] = []
    used = 0
    for label, text in snippets:
        body = text.strip()
        if not body:
            continue
        if used + len(body) > _SNIPPET_TOTAL_CHARS:
            break
        used += len(body)
        lines.append(f'- {label.strip() or "Excerpt"}: "{body}"')
    if not lines:
        return ""
    return (
        "--- Pinned excerpts ---\n"
        "The user kept these passages as context for this conversation:\n"
        + "\n".join(lines)
        + "\n--- End pinned excerpts ---"
    )


_UNPINNED_MATCH_LIMIT = 2
"""Most unpinned resources to name in one turn -- a short list the user can
act on (open it, or ask a follow-up), not a dump of the whole project."""

_UNPINNED_MIN_OVERLAP = 2
"""Shared terms required before naming an unpinned resource. Two, not one,
keeps a single common word (e.g. "revenue") from surfacing every table in
the project on every turn."""


async def _find_unpinned_project_matches(
    session: AsyncSession,
    *,
    project_id: int | None,
    pinned: set[tuple[str, int]],
    question: str,
) -> list[ActiveResourceContext]:
    """Notice project resources the question is probably about, that aren't
    already pinned to this workspace.

    The workspace only grounds the assistant on what's been dragged in; a
    question can still be about something the user hasn't opened yet ("how
    does this compare to the forecast doc?"). This is a cheap, local
    term-overlap search over the rest of the project -- no extra LLM call,
    no vector index -- and only surfaces a match strong enough to be worth
    naming. It never fetches full content: naming a resource here works the
    same as naming an already-pinned one, and the model still has to reach
    it through the normal SQL/document paths if the answer actually needs it.
    """
    if project_id is None:
        return []
    q_terms = _extract_insight_terms(question)
    if not q_terms:
        return []
    candidates = await list_project_resource_candidates(
        session, project_id=project_id, exclude=pinned
    )
    scored: list[tuple[int, Any]] = []
    for candidate in candidates:
        overlap = len(q_terms & _extract_insight_terms(candidate.searchable_text))
        if overlap >= _UNPINNED_MIN_OVERLAP:
            scored.append((overlap, candidate))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [
        ActiveResourceContext(
            resource_type=c.resource_type,
            resource_id=c.resource_id,
            label=c.label,
            summary=c.summary,
        )
        for _, c in scored[:_UNPINNED_MATCH_LIMIT]
    ]


def _format_unpinned_matches_prompt(matches: list[ActiveResourceContext]) -> str:
    """Name project resources the question may be about, that the user
    hasn't pinned to this workspace.

    Distinct from the active-resource block: those are open right now and
    are the default focus. These are only *available* -- said neutrally, the
    same reasoning as the other blocks here, so the model treats a pinned,
    focused item as primary and only reaches for one of these if the
    question actually needs it.
    """
    if not matches:
        return ""
    lines = "\n".join(f"- {m.summary}" for m in matches)
    return (
        "--- Also in this project, not pinned to this workspace ---\n"
        f"{lines}\n"
        "These are not open in the workspace. Treat any pinned or focused "
        "item above as the primary subject of the question; use one of these "
        "only if the question specifically needs it.\n"
        "--- End ---"
    )


# ── Conversation memory ────────────────────────────────────────────────────
#
# A fixed window of recent turns, sent with the answer-synthesis call so the
# model can resolve follow-ups ("that", "explain more") instead of treating
# every question as the first one. ai-server already formats and re-caps this
# (_format_conversation_history in app/routers/ai_shared.py); these budgets
# keep the request small enough that it never gets there oversized.
#
# Deliberately NOT sent to intent classification or SQL generation: a normal
# analytical question is ~3 LLM calls and an investigation up to 8, so history
# on every call would multiply prefill for no benefit. Classification already
# receives prior_turn, and SQL generation already gets the previous SQL.
#
# Known limitation: this is a window, not memory. A thread longer than the
# budget forgets its oldest turns -- no indexing or rolling summary yet. That
# is the planned revamp, and this is the seam it attaches to.
_HISTORY_MAX_TURNS = 8
"""Turns, not messages -- each contributes up to two role messages below."""
_HISTORY_MSG_CHARS = 600
"""Per message, user and assistant alike: a pasted wall of text in a question
crowds out the conversation just as effectively as a long answer."""
_HISTORY_TOTAL_CHARS = 8000
"""~2,300 tokens of a 20,480-token input window, measured across both roles."""


async def _build_llm_history(
    session: AsyncSession,
    conversation: AnalyticsConversation,
    current_turn: AnalyticsConversationTurn,
) -> list[dict[str, str]]:
    """Recent turns as ``{"role", "content"}`` dicts, oldest to newest.

    Queried rather than read from ``conversation.turns``: that relationship is
    lazily loaded and every caller of ``execute_turn`` hands us a conversation
    without it (both ``load_canonical_conversation`` and the route helper
    default to ``with_turns=False``, and the canonical path loads the row with
    a bare ``SELECT ... FOR UPDATE``). Touching it here would raise
    ``MissingGreenlet`` on an AsyncSession -- and would also pull an entire
    long-lived thread into memory to use its last few turns.

    Only successful turns: a failed turn's ``assistant_message`` is an error
    string, and feeding that back would teach the model that the failure was
    the answer.
    """
    rows = (
        (
            await session.execute(
                select(AnalyticsConversationTurn)
                .where(
                    AnalyticsConversationTurn.conversation_id == conversation.id,
                    AnalyticsConversationTurn.id != current_turn.id,
                    AnalyticsConversationTurn.status == "success",
                )
                .order_by(AnalyticsConversationTurn.sequence.desc())
                .limit(_HISTORY_MAX_TURNS)
            )
        )
        .scalars()
        .all()
    )

    messages: list[dict[str, str]] = []
    for prior in reversed(rows):  # newest-first query, oldest-first prompt
        if prior.user_message:
            messages.append(
                {"role": "user", "content": prior.user_message[:_HISTORY_MSG_CHARS]}
            )
        if prior.assistant_message:
            messages.append(
                {
                    "role": "assistant",
                    "content": prior.assistant_message[:_HISTORY_MSG_CHARS],
                }
            )

    # Drop oldest-first so the most recent exchange always survives; it is the
    # one a follow-up actually refers to.
    while messages and sum(len(m["content"]) for m in messages) > _HISTORY_TOTAL_CHARS:
        messages.pop(0)
    return messages


async def _synthesize_answer(
    context: RequestContext,
    project_id: int,
    question: str,
    *,
    data_result: dict[str, Any] | None = None,
    matched_insights: list[dict[str, Any]] | None = None,
    conversation_id: int | None = None,
    turn_id: int | None = None,
    history: list[dict[str, str]] | None = None,
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
            scope="authorized_project",
            data_result=data_result,
            matched_insights=matched_insights,
            conversation_id=conversation_id,
            turn_id=turn_id,
            history=history or [],
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
    active_resources: list[ActiveResourceContext] | None = None,
    focused_resource: ActiveResourceContext | None = None,
    context_snippets: list[tuple[str, str]] | None = None,
) -> None:
    """Execute a single turn and mutate its persisted fields in place.

    The turn's status, SQL, result cache, chart config, and explanation are
    updated. For data-changing turns, the existing ask-and-run core is used.
    For chart-only turns, no SQL is executed and the prior result is reused.
    """
    prior_turn: AnalyticsConversationTurn | None = None
    if conversation.last_successful_turn_id is not None:
        prior_turn = await session.get(AnalyticsConversationTurn, conversation.last_successful_turn_id)
    # Built once here and consumed by whichever answer path this turn takes --
    # the document-Q&A bypass below or the analytical synthesis at the end.
    # Same shape as prior_turn above: one query up front, local variable after.
    history = await _build_llm_history(session, conversation, turn)
    question = turn.user_message
    raw_question = question

    try:
        attachment_context = await build_attachment_context(
            session, context.tenant_id, context.user_id, conversation.id, attachment_ids or []
        )
    except AttachmentAuthorizationError as exc:
        turn.status = "error"
        turn.error_code = "attachment_unauthorized"
        turn.assistant_message = str(exc)
        return
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
        conversation_id=conversation.id,
        turn_id=turn.id,
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

    active_resource_prompt = _format_active_resource_prompt(active_resources, focused_resource)
    if active_resource_prompt:
        # Same pattern as attachment_context above: the active workspace items
        # ground the model's prompts only, never the persisted user message.
        question = f"{active_resource_prompt}\n\n{question}"
        sql_question = f"{active_resource_prompt}\n\n{sql_question}"

    unpinned_matches = await _find_unpinned_project_matches(
        session,
        project_id=conversation.project_id,
        pinned={(r.resource_type, r.resource_id) for r in (active_resources or [])},
        # The raw message, not `question`: by this point `question` may
        # already carry the attachment/active-resource prompt blocks
        # prepended above, and scoring against those would match on their
        # own scaffolding words ("workspace", "currently", "open") rather
        # than what the user actually asked.
        question=turn.user_message,
    )
    unpinned_prompt = _format_unpinned_matches_prompt(unpinned_matches)
    if unpinned_prompt:
        question = f"{unpinned_prompt}\n\n{question}"
        sql_question = f"{unpinned_prompt}\n\n{sql_question}"

    snippet_prompt = _format_context_snippets(context_snippets)
    if snippet_prompt:
        question = f"{snippet_prompt}\n\n{question}"
        sql_question = f"{snippet_prompt}\n\n{sql_question}"

    # A clarification intent from the classifier is an ambiguous phrasing, not a
    # reason to give up. Treat it like a new analysis so the SQL path gets a
    # chance to answer; the ask-and-run core falls back to a prose/KG answer if
    # it cannot ground the question on a data source.
    if intent == ConversationalIntent.CLARIFICATION:
        intent = ConversationalIntent.NEW_ANALYSIS
        turn.intent_type = intent

    # A root-cause ("why") question can read to the classifier as a request
    # to explain the prior result -- especially as a repeated/follow-up turn,
    # where has_prior_result nudges it toward EXPLAIN -- but the user is
    # asking why a number is what it is, not for the SQL/methodology behind
    # it. EXPLAIN returns before the investigation check further down ever
    # runs, so left uncorrected this silently skips the investigation agent
    # every time. Route it like a new analysis instead so that check gets a
    # chance to run.
    if intent == ConversationalIntent.EXPLAIN and _is_investigative_question(question):
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
    # Insight / the untethered "ai_assistant" surface) so a follow-up can
    # switch projects and a question like "Show me IT backup jobs" routes to
    # the IT project even if the conversation was previously pinned to
    # Manufacturing. Project Insights AND Project Workspace ("Workspace —
    # <project>", opened from inside a specific project) are both page-scoped
    # -- canonical_conversations.canonical_scope_key() requires a project_id
    # for both and keys them per-project, exactly like project_insights -- so
    # neither should ever have its project silently swapped mid-conversation.
    # Live incident: a project_workspace conversation titled "Workspace —
    # Sales" answered "Show my top performers" from an unrelated project's
    # data entirely (a movies dataset) because this check excluded
    # project_workspace and let the semantic resolver below override it with
    # no anchor at all on the conversation's first turn.
    is_project_scoped = conversation.surface in ("project_insights", "project_workspace")
    project_id = conversation.project_id
    resolved_project_id: int | None = None
    if not is_project_scoped:
        resolved = await resolve_business_insight_project(
            session, context, question,
            anchor_project_id=conversation.project_id if prior_turn is not None else None,
        )
        if resolved.status == "resolved" and resolved.project_id:
            resolved_project_id = resolved.project_id
            project_id = resolved.project_id
            # conversation.project_id is only committed once this turn actually
            # succeeds (see the two `turn.status = "success"` branches below) --
            # not here. Committing an unproven resolution poisons the
            # conversation's anchor even when the resolved project turns out to
            # have no matching source and the turn fails outright, which is
            # exactly the failure mode that let a wrong first guess persist
            # across follow-up turns instead of self-correcting.

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

    # Dashboard commands generate a validated, best-practice design (the same
    # profiling the guided designer's review step does) and attach it as a
    # pending proposal the chat itself previews -- no modal. A follow-up
    # message while that proposal is still pending ("remove the SLA chart",
    # "add backlog by priority") is folded onto the original request and the
    # whole design is regenerated, rather than requiring an explicit new
    # create-dashboard command. An explicit fresh command always starts over.
    from sqlalchemy import select as _select

    preceding_turn = await session.scalar(
        _select(AnalyticsConversationTurn).where(
            AnalyticsConversationTurn.conversation_id == conversation.id,
            AnalyticsConversationTurn.sequence == turn.sequence - 1,
        )
    )
    preceding_proposal = (
        (preceding_turn.explanation or {}).get("artifactProposal")
        if preceding_turn is not None
        else None
    )
    is_dashboard_refinement = bool(
        preceding_proposal
        and preceding_proposal.get("kind") == "dashboard"
        and preceding_proposal.get("status") == "pending"
        and intent not in (ConversationalIntent.CREATE_QUERY, ConversationalIntent.CREATE_DASHBOARD)
    )
    if intent == ConversationalIntent.CREATE_DASHBOARD or is_dashboard_refinement:
        # preceding_proposal is only required -- and only read below -- on
        # the refinement path. A fresh CREATE_DASHBOARD command (the common
        # case: the first dashboard request in a conversation) legitimately
        # has no preceding turn, so asserting it unconditionally here made
        # every first-time "create a dashboard" chat command crash.
        if is_dashboard_refinement:
            assert preceding_proposal is not None
            design_prompt = f"{preceding_proposal['prompt']}\n\nAdditional instruction: {raw_question}"
        else:
            design_prompt = raw_question
        await _propose_dashboard(
            session,
            context,
            turn,
            project_id=project_id,
            prompt=design_prompt,
            governance=pre_decision.to_explanation_dict(),
        )
        if resolved_project_id is not None:
            conversation.project_id = resolved_project_id
        return

    # "Save this result as a query" reuses the preceding executed SQL/result;
    # it must not ask the model to regenerate a potentially different query.
    if (
        intent == ConversationalIntent.CREATE_QUERY
        and prior_turn is not None
        and prior_turn.result_cache is not None
        and prior_turn.sql
        and is_save_existing_query_request(raw_question)
    ):
        turn.sql = prior_turn.sql
        turn.sql_fingerprint = prior_turn.sql_fingerprint
        turn.result_cache = prior_turn.result_cache
        turn.result_metadata = prior_turn.result_metadata
        turn.chart_config = prior_turn.chart_config
        turn.datasource_context = prior_turn.datasource_context
        turn.explanation = _build_explanation(
            turn.sql,
            turn.result_cache,
            turn.chart_config,
            governance=pre_decision.to_explanation_dict(),
        )
        turn.explanation["artifactProposal"] = _artifact_proposal(
            "query",
            raw_question,
            sql=turn.sql,
            data_sources=list((turn.datasource_context or {}).get("dataSourcesUsed") or []),
        )
        turn.assistant_message = (
            "The previous validated result is ready to save as a governed project query."
        )
        turn.status = "success"
        if resolved_project_id is not None:
            conversation.project_id = resolved_project_id
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
            history=history,
            scope="authorized_project",
            include_query_history=False,
            include_dashboard_context=False,
            grounding_evidence=grounding_dict,
        )
        if isinstance(prose, dict) and prose.get("ai_unavailable"):
            # Distinct from "no relevant document found" -- the AI service
            # itself could not be reached, so claiming success with a
            # "couldn't find a relevant document" message would misrepresent
            # an outage as a completed (if empty) search.
            turn.status = "error"
            turn.error_code = "ai_unavailable"
            turn.assistant_message = "The AI service is currently unavailable. Please try again shortly."
            return
        answer = (
            prose.get("answer") if isinstance(prose, dict) else (str(prose) if prose else "")
        )
        turn.assistant_message = (
            answer
            or "I couldn't find a relevant document for that question. Try rephrasing or checking the Reference Library."
        )
        turn.status = "success"
        if resolved_project_id is not None:
            conversation.project_id = resolved_project_id
        turn.intent_type = ConversationalIntent.DOCUMENT_QA
        turn.result_metadata = {
            "documentQa": {
                "referenceDocumentCount": len(grounding.reference_documents),
                "kgNodeCount": len(grounding.kg_nodes),
            }
        }
        return

    # A root-cause ("why") question can benefit from running several
    # targeted sub-questions instead of one -- run the investigation agent
    # first and only fall back to the normal single-query path if it never
    # produces a successful result, so this can only add capability, never
    # regress the standard path.
    #
    # Check (and pass through) the user's original `question`, not
    # `sql_question`: the conversation-turn classifier rewrites `why`
    # framing into a focused, presentation-free data question for SQL
    # generation (e.g. "why is the failure rate rising" -> "backup job
    # failure rate trend over time"), which is exactly the wording that
    # strips the investigative signal this check and the investigation
    # agent's own root-cause planning both depend on.
    investigation_steps: list[dict[str, Any]] = []
    run: dict[str, Any] | None = None
    if _is_investigative_question(question):
        run, investigation_steps = await _run_investigation(
            session,
            context,
            project_id,
            question,
            datasource_id,
            project_context=project_context,
            conversation_id=conversation.id,
            turn_id=turn.id,
        )
    if run is None:
        run = await _run_analytical_turn(
            session,
            context,
            project_id,
            sql_question,
            prior_turn,
            datasource_id,
            project_context=project_context,
            conversation_id=conversation.id,
            turn_id=turn.id,
        )
        investigation_steps = []

    turn.sql = run.get("sql") or None
    turn.project_context_version = project_context.get("version") if project_context else None
    turn.sql_fingerprint = _sql_fingerprint(turn.sql)

    if run.get("status") == "ai_unavailable":
        # The AI service itself could not be reached, as opposed to
        # "generation_error"/"execution_error" below (the AI responded but
        # couldn't build/run a valid query) -- kept as its own branch for a
        # more specific default message and error_code than the generic
        # fallback below would give it.
        turn.status = "error"
        turn.error_code = "ai_unavailable"
        turn.assistant_message = (
            run.get("error")
            or "The AI service is currently unavailable. Please try again shortly."
        )
        turn.result_metadata = {"error": run.get("error"), "errorDetails": run.get("errorDetails")}
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
    turn.result_metadata = (
        {**profile, "investigation": {"steps": investigation_steps}}
        if investigation_steps
        else profile
    )
    turn.chart_config = chart_config
    turn.explanation = _build_explanation(
        turn.sql, result_cache, chart_config, governance=post_decision.to_explanation_dict()
    )
    turn.datasource_context = {"dataSourcesUsed": run.get("dataSourcesUsed", [])}
    if intent == ConversationalIntent.CREATE_QUERY:
        turn.explanation["artifactProposal"] = _artifact_proposal(
            "query",
            raw_question,
            sql=turn.sql,
            data_sources=list(run.get("dataSourcesUsed") or []),
        )
    turn.status = "success"
    if resolved_project_id is not None:
        conversation.project_id = resolved_project_id

    # If the live result is on-topic but there is a strong, precomputed Insight
    # Card that adds deeper grounded analysis, return both. The Insight Card is
    # surfaced below the live chart so the user gets the fresh numbers plus the
    # existing diagnostics and proposed actions.
    matched_insights_for_synthesis: list[dict[str, Any]] | None = None
    live_score = _live_query_score(
        question, result_cache, run.get("dataSourcesUsed") or []
    )
    if live_score < 0.95:
        # LLM-verified relevance (the default), not the raw deterministic
        # data-shape score alone -- a keyword-overlap-only match can pick a
        # topically-adjacent but wrong card (e.g. a "budget vs forecast"
        # card offered for a "budget vs actual" question) purely because
        # its summary shares filler words with the question. See
        # insight_card_match.py's own documented failure mode.
        insight_matches = await find_matching_insight_cards(
            session,
            context=context,
            tenant_id=context.tenant_id,
            project_id=project_id,
            question=question,
            allow_cross_project=not is_project_scoped,
            max_cards=2,
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
    if investigation_steps:
        # Give the synthesizer the full investigation trail (see
        # ai_ask.py's _format_data_result), not just the last sub-query in
        # isolation, so the answer can explain WHY by citing which specific
        # sub-question surfaced which finding.
        data_result["steps"] = investigation_steps
    synthesized = await _synthesize_answer(
        context,
        project_id,
        question,
        data_result=data_result,
        matched_insights=matched_insights_for_synthesis,
        conversation_id=conversation.id,
        turn_id=turn.id,
        history=history,
    )
    turn.assistant_message = (
        synthesized
        or run.get("explanation")
        or _answer_text(columns, bounded_rows)
    )
