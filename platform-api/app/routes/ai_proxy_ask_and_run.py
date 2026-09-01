"""Ask-and-run: generate SQL for a question, execute it, return rows.

Also powers the Recommended Queries preview, and owns the SQL execution,
repair and response-envelope helpers both endpoints share."""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.file_source_meta import FileSourceMeta
from app.services import ai_intelligence_client as ai
from app.services import ask_pipeline, insight_registry
from app.services.ai_grounding import gather_grounding_evidence
from app.services.analytical_method_engine import analyze as analyze_methods
from app.services.analytical_method_engine import data_profiler
from app.services.analytical_method_engine.config import EngineMode, get_engine_mode
from app.services.insight_card_match import find_matching_insight_card
from app.services.intent_engine import IntentDecision, classify_intent
from app.services.presentation_engine import PresentationMode, mode_for_ask_and_run
from app.services.presentation_engine import describe as describe_presentation
from app.services.response_envelope import ResponseEnvelope
from app.services.sql_repair_agent import is_read_only_select as _is_read_only_select
from app.services.sql_repair_agent import run_repair_loop
from app.services.teiid_sql import (
    add_missing_from_clause,
    collapse_bare_following_parens,
    normalize_teiid_identifiers,
    normalize_teiid_string_filters,
    normalize_teiid_timestamps,
    rebuild_group_by_from_select,
)

from .ai_proxy_schemas import (
    AIAskAndRunRequest,
    AICardContext,
    AIGenerateQueryPreviewRequest,
)
from .ai_proxy_shared import (
    _build_source_catalog,
    _check_project_access,
    _detect_datasource,
    _kg_context,
    _relationship_hints,
    _shorten_ai_name,
)

logger = logging.getLogger(__name__)
router = APIRouter()

async def _retrieve_stored_insight_query(
    session: AsyncSession,
    context: RequestContext,
    project_id: int | None,
    question: str,
) -> dict[str, Any] | None:
    """Answer "show me the query for <insight>" from the stored card.

    Returns ``None`` unless the question is a query request AND resolves to a
    single card with stored SQL — every other question falls through to normal
    generation. Fail-open: any error returns ``None``.
    """
    try:
        if not insight_registry.is_query_request(question):
            return None
        cards = await insight_registry.load_tenant_insight_cards(
            session,
            tenant_id=context.tenant_id,
            project_id=project_id,
            user_id=context.user_id,
        )
        if not cards:
            return None
        match = insight_registry.resolve_insight_reference(question, cards)
        if match.ambiguous:
            clarifying: dict[str, Any] = {
                "answer": insight_registry.format_ambiguous(match.ambiguous),
                "model_used": "tablescope-direct",
                "request_id": "",
                "context_summary": {},
                "sql": "",
                "columns": [],
                "rows": [],
                "status": "success",
                "answerType": "text",
                "retrievedFromInsight": None,
            }
            _attach_presentation(clarifying)
            return clarifying
        if not match.resolved or match.match is None:
            return None
        answer = insight_registry.stored_query_answer(match.match)
        if answer is None:
            return None
        _attach_presentation(answer)
        return answer
    except Exception:
        logger.exception("stored-insight query retrieval failed")
        return None


async def _insight_card_context(
    session: AsyncSession,
    context: RequestContext,
    project_id: int | None,
    question: str,
) -> str:
    """Grounding for a question that names an insight card.

    Without this the ask paths saw knowledge-graph context only — documents,
    KPIs and tables — so "show me the query for <card title>" had nothing to
    retrieve and the model invented a plausible-looking SQL query instead. Cards
    already store their real SQL; this makes that retrievable.

    Best-effort: any failure returns "" and the answer proceeds as before.
    """
    try:
        cards = await insight_registry.load_tenant_insight_cards(
            session,
            tenant_id=context.tenant_id,
            project_id=project_id,
            user_id=context.user_id,
        )
        return insight_registry.build_insight_context(question, cards)
    except Exception:
        logger.exception("Failed to build insight-card context")
        return ""


# The ask-and-run mini-renderer (``web-ui/.../ai-result-view.tsx``) draws a
# subset of the full chart vocabulary. Map the Visualization Engine's decision
# onto what this surface can render, so the decision stays unified while the
# rendered output never exceeds this surface's capability. Charts this surface
# cannot shape meaningfully (scatter) degrade to a table rather than a
# misleading bar.
def _suggest_visualization(
    columns: list[str], rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """Pick a sensible default chart for a result set (deterministic).

    Delegates the decision to the single Universal Visualization Engine
    (``app.services.visualization_engine``) so ask-and-run, Home cards, and
    dashboards all agree on the same chart for the same shape, then maps the
    engine's decision onto the subset this surface can render.
    """
    if not columns or not rows:
        return {"type": "table"}

    # Delegate to the shared ask pipeline so every conversational surface uses
    # the same chart-fit ranking the insight cards use. The old
    # ``_ASK_AND_RUN_SURFACE`` narrowing collapsed 26 families onto five and
    # turned scatter/heatmap/boxplot answers into tables; the renderer draws all
    # of them, so the narrowing only lost information.
    presentation = ask_pipeline.resolve_presentation(columns, rows)
    viz = dict(presentation.chart)
    # Keep the legacy field names this surface's clients already read.
    if "labelColumn" in viz:
        viz["xField"] = viz["labelColumn"]
    value_columns = viz.get("valueColumns") or []
    if value_columns:
        viz["yField"] = value_columns[0]
        if len(value_columns) > 1:
            viz["y2Field"] = value_columns[1]
    if viz.get("subtype"):
        viz["chartStyle"] = viz["subtype"]
    if presentation.candidates:
        viz["candidates"] = presentation.candidates
    return viz


_LIMIT_RE = re.compile(r"\blimit\s+\d+\s*$", re.IGNORECASE)


def _apply_row_limit(sql: str, max_rows: int) -> str:
    """Ensure a preview query is bounded so it never runs unbounded."""
    trimmed = sql.strip().rstrip(";").rstrip()
    if _LIMIT_RE.search(trimmed):
        return trimmed
    return f"{trimmed} LIMIT {max_rows}"


async def _execute_project_sql(
    session: AsyncSession,
    context: RequestContext,
    project_id: int,
    sql: str,
) -> dict[str, Any]:
    """Execute SQL against the project's VDB and return ``{columns, rows}``."""
    from app.routes.query import (
        _auto_cast_aggregates,
        _resolve_vdb_database,
        _run_sql,
    )
    from app.services.tenant_teiid_resolver import TenantTeiidResolver

    database = await _resolve_vdb_database(
        session=session, context=context, project_id=project_id
    )
    endpoint = await TenantTeiidResolver(session).resolve_for_org(context.tenant_id)
    # Normalise PostgreSQL-style timestamp literals/functions before casting
    # aggregates, so the first execution attempt is more likely to succeed.
    normalized = normalize_teiid_timestamps(sql)
    return await _run_sql(
        database=database,
        sql=_auto_cast_aggregates(normalized),
        teiid_host=endpoint.pg_host,
        teiid_port=endpoint.pg_port,
    )


async def _project_table_schema(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: int,
) -> list[dict[str, Any]]:
    """Build the exact per-source column schema for SQL repair.

    Shape: ``[{"table": view, "columns": [{"name", "type"}]}]`` — the same
    contract the AI server's ``repair-sql-step`` endpoint consumes so it can
    rewrite a rejected query using real columns/types (never invented ones).
    """
    rows = (
        await session.scalars(
            select(FileSourceMeta).where(
                FileSourceMeta.project_id == project_id,
                FileSourceMeta.tenant_id == tenant_id,
                FileSourceMeta.archived.is_(False),
            )
        )
    ).all()
    schema: list[dict[str, Any]] = []
    for ds in rows:
        columns = [
            {"name": str(c.get("name")), "type": str(c.get("type") or "")}
            for c in (ds.column_types or [])
            if isinstance(c, dict) and c.get("name")
        ]
        schema.append({"table": ds.view_name, "columns": columns})
    return schema


async def _column_samples_for_tables(
    session: AsyncSession,
    context: RequestContext,
    project_id: int,
    allowed_tables: list[str],
    table_schema: list[dict[str, Any]],
) -> tuple[dict[str, str], dict[str, str]]:
    """Build per-column type and one sample-value map for the allowed tables.

    The sample values drive ``normalize_teiid_timestamps`` so the AI's guessed
    date masks (e.g. ``'M/d/yyyy'`` on an ISO column) are corrected to the
    column's real format before Teiid sees them.
    """
    column_types: dict[str, str] = {}
    for entry in table_schema:
        table = entry.get("table")
        if table not in allowed_tables:
            continue
        for col in entry.get("columns", []):
            if isinstance(col, dict):
                name = col.get("name")
                col_type = col.get("type") or ""
            else:
                name = col
                col_type = ""
            if name:
                column_types[str(name)] = str(col_type)

    column_samples: dict[str, str] = {}
    for table in allowed_tables:
        try:
            probe = await _execute_project_sql(
                session, context, project_id,
                f'SELECT * FROM "{table}" LIMIT 1',
            )
            if not probe or not probe.get("rows"):
                continue
            for col, val in probe["rows"][0].items():
                if val is not None:
                    column_samples[str(col)] = str(val)
        except Exception as exc:
            logger.warning(
                "Could not sample table %s for date masks: %s", table, exc
            )

    return column_samples, column_types


async def _execute_with_repair(
    session: AsyncSession,
    context: RequestContext,
    *,
    project_id: int,
    sql: str,
    allowed_tables: list[str],
    max_rows: int,
    table_schema: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, str, str]:
    """Execute SQL; on an engine error, run the SQL self-repair agent to fix
    it using the exact Teiid error + real schema, then re-run.

    Closes the same self-repair loop the dashboard path uses so Teiid quirks
    (unsupported functions like DATEDIFF, un-CAST string arithmetic, alias/
    GROUP BY mistakes) heal automatically instead of surfacing as a dead-end
    error. Returns ``(result_or_none, final_sql, last_error)``.

    The bounded decision loop itself lives in ``sql_repair_agent`` (shared
    with the saved-query/dashboard execution path) -- this only supplies the
    two things specific to the chat path: this module's own deterministic
    rewrite pipeline, and the row-limited execution call.
    """
    column_samples, column_types = await _column_samples_for_tables(
        session, context, project_id, allowed_tables, table_schema
    )

    async def _normalize(candidate: str) -> str:
        candidate = add_missing_from_clause(candidate, table_schema)
        candidate = normalize_teiid_identifiers(candidate, table_schema)
        candidate = normalize_teiid_string_filters(candidate, table_schema)
        candidate = normalize_teiid_timestamps(
            candidate,
            column_samples=column_samples,
            column_types=column_types,
        )
        candidate = collapse_bare_following_parens(candidate)
        candidate = rebuild_group_by_from_select(candidate)
        return candidate

    async def _execute(candidate: str) -> dict[str, Any]:
        bounded = _apply_row_limit(candidate, max_rows)
        return await _execute_project_sql(session, context, project_id, bounded)

    return await run_repair_loop(
        initial_sql=sql,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        project_id=project_id,
        allowed_tables=allowed_tables,
        table_schema=table_schema,
        column_samples=column_samples,
        column_types=column_types,
        normalize=_normalize,
        execute=_execute,
    )


def _ai_generation_error(detail: Any) -> tuple[str, dict[str, Any]]:
    """Translate an AI-server generation failure's ``detail`` into a friendly
    message + details.

    Returns ``(message, details)`` where ``message`` is safe to show a user and
    ``details`` carries expandable technical context (matched sources, validation
    error) — never a raw dict repr or stack trace. ``detail`` may come from an
    ``HTTPException`` raised locally or from an ``AIUnavailableError.detail``
    parsed out of the AI server's own 4xx response body -- both use the same
    ``{"message", "reason", "suggested_sources"}`` shape.
    """
    friendly = "We could not safely build a query for this question."
    details: dict[str, Any] = {}
    if isinstance(detail, dict):
        message = detail.get("message")
        if message:
            friendly = str(message)
        if detail.get("reason"):
            details["validationError"] = str(detail["reason"])
        sources = detail.get("suggested_sources")
        if isinstance(sources, list) and sources:
            details["matchedSources"] = [
                (s.get("name") if isinstance(s, dict) else str(s))
                for s in sources
            ]
    elif isinstance(detail, str) and detail:
        details["validationError"] = detail
    return friendly, details


def _matched_insight_message(result: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """The "live query failed, here's why" clause for a matched-card fallback.

    Returns ``(reason_sentence, error_details)``; the caller appends the card
    citation itself so the failure is stated plainly (a real regression on a
    question that should trivially succeed must never hide behind a
    good-looking card citation) without the combined sentence reading as
    "nothing was found" -- a card was found and does answer the question.
    Mirrors ``conversational_analytics.execute_turn()``'s equivalent wording
    so the same fallback reads the same way on every surface.
    """
    error_details = result.get("errorDetails")
    validation_error = (
        error_details.get("validationError")
        if isinstance(error_details, dict)
        else None
    )
    detail_bits = list(dict.fromkeys(
        d for d in (result.get("error"), validation_error) if d
    ))
    detail_suffix = f" ({'; '.join(detail_bits)})" if detail_bits else ""
    reason = (
        "I couldn't build a live query for this question"
        if result.get("status") == "generation_error"
        else "I couldn't run a live query against your data just now"
    )
    return f"{reason}{detail_suffix}.", {
        "validationError": validation_error,
    } if validation_error else {}


async def _generate_sql_for_question(
    session: AsyncSession,
    context: RequestContext,
    project_id: int,
    question: str,
    *,
    preferred_sources: list[str] | None = None,
    relevant_columns: list[str] | None = None,
    grounding_evidence: dict[str, Any] | None = None,
    conversation_id: int | None = None,
    turn_id: int | None = None,
) -> dict[str, Any]:
    """Generate SQL for a natural-language question via the AI server.

    Returns the raw AI result dict (``sql``/``explanation``/``selected_sources``)
    plus the resolved ``allowed_tables``. Raises HTTPException on failure so the
    caller can convert it into a structured, non-fatal modal error.

    ``preferred_sources``/``relevant_columns`` come from the Project Semantic
    Source Resolver and steer the model toward the authorized source the
    request maps to.
    """
    ds_stmt = select(FileSourceMeta).where(
        FileSourceMeta.project_id == project_id,
        FileSourceMeta.tenant_id == context.tenant_id,
        FileSourceMeta.archived.is_(False),
    )
    ds_result = await session.execute(ds_stmt)
    sources = list(ds_result.scalars())
    allowed_tables = [ds.view_name for ds in sources]
    # Evidence-backed join candidates (same discovery engine the dashboard
    # pipeline uses) -- lets a query combine measures that live in separate
    # sources (e.g. actuals vs. a forecast table) instead of being
    # restricted to one table with no way to express that.
    relationship_hints = _relationship_hints(sources)

    source_catalog = await _build_source_catalog(
        session, context, project_id=project_id
    )
    # AIUnavailableError propagates as-is (not wrapped in HTTPException) so
    # callers can tell "the AI service itself is unreachable" apart from "the
    # AI service responded but declined/failed to build a valid query" --
    # collapsing both into the same generic failure is what let an AI-server
    # outage silently resolve to a matched Insight Card instead of a clear
    # error, with no way for the caller to know that's what happened.
    ai_result = await ai.generate_sql(
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        project_id=project_id,
        prompt=question,
        allowed_tables=allowed_tables,
        source_catalog=source_catalog,
        preferred_sources=preferred_sources or [],
        relevant_columns=relevant_columns or [],
        knowledge_graph_context=await _kg_context(session, context, project_id),
        grounding_evidence=grounding_evidence,
        relationship_hints=relationship_hints,
        conversation_id=conversation_id,
        turn_id=turn_id,
    )
    if not isinstance(ai_result, dict):
        raise ai.AIUnavailableError("AI server returned an invalid response")
    ai_result["_allowed_tables"] = allowed_tables
    return ai_result


async def _resolve_action_sources(
    session: AsyncSession,
    context: RequestContext,
    *,
    project_id: int,
    question: str,
    intent: str,
    source: str | None = None,
    card_context: AICardContext | None = None,
) -> Any:
    """Run the Project Semantic Source Resolver for one AI action.

    A user-picked ``source`` (e.g. chosen from a prior clarification) is treated
    as an authorized card source so the resolver locks onto it.
    """
    from app.services.project_source_resolver import resolve_project_source

    ctx: dict[str, Any] = (
        card_context.to_resolver_context() if card_context else {}
    )
    if source:
        ctx = {**ctx, "sourceTables": [source]}
    return await resolve_project_source(
        session,
        tenant_id=context.tenant_id,
        project_id=project_id,
        question=question,
        intent=intent,
        card_context=ctx or None,
    )


async def _ask_and_run_core(
    session: AsyncSession,
    context: RequestContext,
    *,
    project_id: int,
    question: str,
    max_rows: int,
    source: str | None = None,
    card_context: Any | None = None,
    conversation_id: int | None = None,
    turn_id: int | None = None,
) -> dict[str, Any]:
    """Resolve a source, generate SQL, execute it, and return the result dict.

    Shared by the ask-and-run action endpoint and the AI Assistant chat so both
    ground answers on real executed data. Never raises on a generation/execution
    failure — returns a structured ``status`` with SQL + error instead.
    """
    # A question that asks to SEE an insight's query is a RETRIEVAL, not a
    # generation. Generating SQL here is exactly how an invented query got
    # presented as the card's query; the card stores the real one.
    retrieved = await _retrieve_stored_insight_query(
        session, context, project_id, question
    )
    if retrieved is not None:
        return retrieved

    resolver = await _resolve_action_sources(
        session, context,
        project_id=project_id,
        question=question,
        intent="question_answer",
        source=source,
        card_context=card_context,
    )

    # Gather proactive grounding evidence before generation.
    # This runs before SQL generation so the prompt can include retrieved
    # document passages, query-aware KG nodes, and ranked governed KPIs.
    grounding = await gather_grounding_evidence(
        session,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        project_id=project_id,
        question=question,
        relevant_columns=resolver.relevant_columns,
    )
    grounding_evidence = grounding.model_dump() if grounding else None
    grounding_manifest = grounding.manifest() if grounding else None

    # A question asked *from* a card carries that card with it. Grounding the
    # prompt in the finding — its text, its method and the query it was computed
    # from — is what makes "what is driving this?" dig into that insight instead
    # of being answered against the project at large.
    generation_question = question
    if card_context is not None and hasattr(card_context, "to_card"):
        followup = ask_pipeline.build_insight_followup(question, card_context.to_card())
        generation_question = ask_pipeline.followup_prompt(followup)

    try:
        ai_result = await _generate_sql_for_question(
            session, context, project_id, generation_question,
            preferred_sources=resolver.preferred_sources,
            relevant_columns=resolver.relevant_columns,
            grounding_evidence=grounding_evidence,
            conversation_id=conversation_id,
            turn_id=turn_id,
        )
    except ai.AIUnavailableError as exc:
        if exc.declined:
            # The AI server was reached and responded -- it just rejected
            # this specific request (e.g. the SQL generator's structured 422
            # "needs clarification"). That's the same shape as the
            # HTTPException branch below, so it gets the same friendly
            # message and the same downstream Insight-Card fallback instead
            # of a false "the AI service is unavailable".
            friendly, details = _ai_generation_error(exc.detail)
            return {
                "question": question,
                "sql": "",
                "columns": [],
                "rows": [],
                "suggestedVisualization": {"type": "table"},
                "explanation": "",
                "dataSourcesUsed": [],
                "status": "generation_error",
                "error": friendly,
                "errorDetails": details,
                "groundingManifest": grounding_manifest,
            }
        # A genuine outage (unreachable, timed out, busy): a matched Insight
        # Card or KG prose answer would be standing in for the AI, not
        # summarizing it -- exactly the silent-fallback behavior that made
        # an AI-server outage look like a working (if irrelevant) answer.
        # Callers must surface this as a hard error, not fall further back.
        return {
            "question": question,
            "sql": "",
            "columns": [],
            "rows": [],
            "suggestedVisualization": {"type": "table"},
            "explanation": "",
            "dataSourcesUsed": [],
            "status": "ai_unavailable",
            "error": "The AI service is currently unavailable. Please try again shortly.",
            "errorDetails": {"aiError": str(exc)},
            "groundingManifest": grounding_manifest,
        }
    except HTTPException as exc:
        friendly, details = _ai_generation_error(exc.detail)
        return {
            "question": question,
            "sql": "",
            "columns": [],
            "rows": [],
            "suggestedVisualization": {"type": "table"},
            "explanation": "",
            "dataSourcesUsed": [],
            "status": "generation_error",
            "error": friendly,
            "errorDetails": details,
            "groundingManifest": grounding_manifest,
        }

    allowed_tables = ai_result.pop("_allowed_tables", [])
    sql = (ai_result.get("sql") or "").strip().rstrip(";")
    if not sql or not _is_read_only_select(sql):
        return {
            "question": question,
            "sql": sql if sql else "",
            "columns": [],
            "rows": [],
            "suggestedVisualization": {"type": "table"},
            "explanation": ai_result.get("explanation", ""),
            "dataSourcesUsed": [],
            "status": "generation_error",
            "error": "We could not safely build a query for this question.",
            "errorDetails": {"sql": sql} if sql else {},
            "groundingManifest": grounding_manifest,
        }

    table_schema = await _project_table_schema(
        session, tenant_id=context.tenant_id, project_id=project_id
    )
    result, sql, exec_error = await _execute_with_repair(
        session, context,
        project_id=project_id,
        sql=sql,
        allowed_tables=allowed_tables,
        max_rows=max_rows,
        table_schema=table_schema,
    )
    if result is None:
        return {
            "question": question,
            "sql": sql,
            "columns": [],
            "rows": [],
            "suggestedVisualization": {"type": "table"},
            "explanation": ai_result.get("explanation", ""),
            "dataSourcesUsed": [_detect_datasource(sql, allowed_tables) or ""],
            "status": "execution_error",
            "error": "We could not run this query against the project's data.",
            "errorDetails": {
                "sql": sql,
                "executionError": exec_error,
            },
            "groundingManifest": grounding_manifest,
        }

    columns = result.get("columns", [])
    rows = result.get("rows", [])[:max_rows]
    used = _detect_datasource(sql, allowed_tables)
    response: dict[str, Any] = {
        "question": question,
        "sql": sql,
        "columns": columns,
        "rows": rows,
        "suggestedVisualization": _suggest_visualization(columns, rows),
        "explanation": ai_result.get("explanation", ""),
        "dataSourcesUsed": [used] if used else [],
        "status": "success",
        "error": None,
        "groundingManifest": ai_result.get("grounding_manifest") or grounding_manifest,
    }
    decision = _classify_intent_safe(question, columns, rows)
    if decision is not None:
        response["intent"] = decision.to_dict()
    await _attach_analytical_envelope(
        session, context, question, columns, rows, response,
        intent_hint=decision.analysis_intent if decision else None,
    )
    await _attach_ask_analytics(
        response, session, tenant_id=context.tenant_id, question=question
    )
    # Ground the answer in the insight card the question names, when it names
    # one, so follow-ups ("why did that happen?", "break it down") continue that
    # card's story with its real method and sources instead of starting over.
    insight_ctx = await _insight_card_context(session, context, project_id, question)
    if insight_ctx:
        response["insightContext"] = insight_ctx
    _attach_presentation(response)
    return response


def _attach_presentation(response: dict[str, Any]) -> None:
    """Stamp the shared ``presentation`` descriptor + ``ResponseEnvelope``.

    Non-breaking, fail-closed. ``presentation`` is the ``{mode, sections}``
    descriptor from the one section registry; ``envelope`` is the shared
    :class:`ResponseEnvelope` — the ask-and-run pilot for the M4 fast-follow,
    emitting the surface's data under the unified contract so the frontend can
    read one shape. Existing fields are left untouched. Never raises.
    """
    try:
        mode = mode_for_ask_and_run(
            answer_type=response.get("answerType"),
            has_method_envelope=response.get("analyticalMethod") is not None,
        )
        response["presentation"] = describe_presentation(mode)
        response["envelope"] = _build_ask_and_run_envelope(response, mode)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Presentation engine hook failed: %s", exc)


def _build_ask_and_run_envelope(
    response: dict[str, Any], mode: PresentationMode
) -> dict[str, Any]:
    """Map an ask-and-run response dict onto the shared ``ResponseEnvelope``.

    The prose explanation is the answer for a conversational fallback and the
    (executive) summary for an executed result; None fields are dropped.
    """
    explanation = response.get("explanation") or None
    is_prose = mode is PresentationMode.CONVERSATIONAL
    # A prose answer renders no chart/grid/SQL — don't carry those fields even
    # if the fallback stamped a default table visualization.
    data = None if is_prose else response
    envelope = ResponseEnvelope.build(
        mode,
        status=response.get("status"),
        answer=explanation if is_prose else None,
        summary=explanation if not is_prose else None,
        executive_summary=(
            explanation if mode is PresentationMode.HYBRID else None
        ),
        sql=(data or {}).get("sql") or None,
        columns=(data or {}).get("columns") or None,
        rows=(data or {}).get("rows") or None,
        chart=(data or {}).get("suggestedVisualization") or None,
        method_envelope=response.get("analyticalMethod"),
        sources=response.get("dataSourcesUsed") or None,
        intent=response.get("intent"),
    )
    return envelope.model_dump(exclude_none=True)


def _classify_intent_safe(
    question: str, columns: list[str], rows: list[Any]
) -> IntentDecision | None:
    """Declared Intent Engine hint over the executed result. Fail-closed.

    Non-authoritative: the returned decision is attached as ``intent`` metadata
    and feeds the Method Engine's Stage-B selector, but never gates the
    try-then-fallback backbone. Any error yields ``None`` so a classifier bug
    can never break the ask path.
    """
    try:
        profile = (
            data_profiler.profile(columns, rows) if columns and rows else None
        )
        return classify_intent(question, profile)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Intent engine hook failed: %s", exc)
        return None


async def _attach_analytical_envelope(
    session: AsyncSession,
    context: RequestContext,
    question: str,
    columns: list[str],
    rows: list[Any],
    response: dict[str, Any],
    *,
    intent_hint: str | None = None,
) -> None:
    """Run the governed Analytical Method Engine over the result set.

    Feature-flagged and fail-closed. In ``readonly`` mode it computes + logs the
    method envelope but never alters the response; in ``hybrid`` it also attaches
    ``analyticalMethod``. ``off`` (default) skips entirely. Tablescope — not the
    LLM — selects the method here; the Intent Engine's ``analysisIntent`` (when
    available) seeds Stage-B selection.
    """
    mode = get_engine_mode()
    if mode == EngineMode.OFF:
        return
    try:
        envelope = await analyze_methods(
            session,
            tenant_id=context.tenant_id,
            columns=columns,
            rows=rows,
            question=question,
            intent=intent_hint,
        )
    except Exception as exc:
        logger.warning("Analytical method engine hook failed: %s", exc)
        return
    if envelope and mode == EngineMode.HYBRID:
        response["analyticalMethod"] = envelope


_CODE_FENCE_RE = re.compile(r"```[a-zA-Z0-9_-]*\n[\s\S]*?(?:```|\Z)")


def _strip_model_markup(text: str) -> str:
    """Remove raw model markup (fenced code blocks) from a prose answer.

    Chat surfaces render plain text, so a leaked ``` block (usually SQL the
    model narrated while thinking) shows up verbatim and confuses users. The
    SQL for data answers is carried separately in structured fields — prose
    must stay prose.
    """
    cleaned = _CODE_FENCE_RE.sub("", text or "").strip()
    return re.sub(r"\n{3,}", "\n\n", cleaned)


async def _forward_prose_answer(
    session: AsyncSession,
    context: RequestContext,
    *,
    project_id: int,
    question: str,
    history: list[dict[str, str]] | None = None,
    scope: str = "project",
    include_query_history: bool = True,
    include_dashboard_context: bool = True,
    grounding_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Free-text answer from the AI server's documents + knowledge-graph path.

    Used as a fallback for analytical/document questions that don't map to a
    single SQL source, so they get a real answer instead of a hard error.
    Grounds the answer in the project's Knowledge Graph when one exists.

    Returns ``{"ai_unavailable": True}`` when the AI service itself could not
    be reached, distinct from an empty ``{}`` "no answer" -- callers must
    treat the two differently: "we tried and had nothing to say" is fine to
    fall further back from, but "we could not even ask" must surface as a
    hard error instead of silently degrading to whatever fallback runs next.
    """
    try:
        result = await ai.ask(
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            project_id=project_id,
            question=question,
            scope=scope,
            include_query_history=include_query_history,
            include_dashboard_context=include_dashboard_context,
            history=history or [],
            knowledge_graph_context=await _kg_context(session, context, project_id),
            grounding_evidence=grounding_evidence,
        )
    except ai.AIUnavailableError:
        return {"ai_unavailable": True}
    return {
        "answer": _strip_model_markup(str((result or {}).get("answer") or "")),
        "model_used": (result or {}).get("model_used", ""),
    }


@router.post("/actions/ask-and-run")
async def ai_ask_and_run(
    req: AIAskAndRunRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """Generate SQL for a question, execute it, and return the results.

    Never raises on a generation/execution failure: returns a structured
    ``status`` (``success`` / ``generation_error`` / ``execution_error`` /
    ``ai_unavailable``) with the SQL (when available) and an error message so
    the modal can render an inline error and reveal the SQL instead of
    navigating away.

    When the live query fails because the AI could not build/run a valid
    query (``generation_error``/``execution_error``), an existing verified
    Insight Card that answers the same question is checked first (scoped to
    this one project only), and only then does the question fall back to the
    free-text documents/knowledge-graph answer — the same precedence the AI
    Assistant uses — so analytical questions are answered as prose instead of
    showing a "couldn't match a source" error.

    ``ai_unavailable`` (the AI service itself is unreachable, not just
    declining the request) skips both of those fallbacks and returns as-is:
    substituting a matched card or KG prose for an AI-server outage would
    make the outage look like a working (if unrelated) answer.
    """
    await _check_project_access(session, context, req.project_id)
    result = await _ask_and_run_core(
        session, context,
        project_id=req.project_id,
        question=req.question,
        max_rows=req.max_rows,
        source=req.source,
        card_context=req.card_context,
    )
    if result.get("status") == "success":
        result["answerType"] = "data"
        return result
    if result.get("status") in ("generation_error", "execution_error"):
        grounding_manifest = result.get("groundingManifest")

        # A question this route can't ground or execute live may already be
        # answered by an existing, verified Insight Card -- same precedence
        # conversational_analytics.execute_turn() applies before falling to
        # unattributed KG prose. Never widened: this route is always asked
        # from inside one specific project (often one specific card), never
        # a cross-project surface.
        card_match = await find_matching_insight_card(
            session,
            context=context,
            tenant_id=context.tenant_id,
            project_id=req.project_id,
            question=req.question,
            allow_cross_project=False,
        )
        if card_match is not None:
            reason, details = _matched_insight_message(result)
            explanation = (
                f"{reason} I found an existing analysis that answers this: "
                f"**{card_match.title}**"
            )
            if card_match.summary:
                explanation += f"\n\n{card_match.summary}"
            match_result: dict[str, Any] = {
                "question": req.question,
                "sql": "",
                "columns": [],
                "rows": [],
                "suggestedVisualization": {"type": "table"},
                "explanation": explanation,
                "dataSourcesUsed": [],
                "status": "success",
                "answerType": "text",
                "error": None,
                "errorDetails": details,
                "matchedInsight": {
                    "insightId": card_match.insight_id,
                    "projectId": card_match.project_id,
                    "projectName": card_match.project_name,
                    "title": card_match.title,
                    "summary": card_match.summary,
                    "chart": card_match.chart,
                    "severity": card_match.severity,
                    "diagnostics": card_match.diagnostics,
                    "proposedActions": card_match.proposed_actions,
                },
                "groundingManifest": grounding_manifest,
            }
            _attach_presentation(match_result)
            return match_result

        prose = await _forward_prose_answer(
            session,
            context,
            project_id=req.project_id,
            question=req.question,
            grounding_evidence=grounding_manifest,
        )
        if prose.get("answer"):
            prose_result: dict[str, Any] = {
                "question": req.question,
                "sql": "",
                "columns": [],
                "rows": [],
                "suggestedVisualization": {"type": "table"},
                "explanation": prose["answer"],
                "model_used": prose.get("model_used", "tablescope-prose"),
                "dataSourcesUsed": [],
                "status": "success",
                "answerType": "text",
                "error": None,
                "groundingManifest": grounding_manifest,
            }
            _attach_presentation(prose_result)
            return prose_result
    return result


@router.post("/actions/generate-query-preview")
async def ai_generate_query_preview(
    req: AIGenerateQueryPreviewRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """Generate + execute a recommended query and return a preview.

    Same generation/execution path as ask-and-run, but returns query metadata
    (title/description) so the Recommended Queries modal can preview then save.
    Non-fatal: returns a structured ``status`` on failure.
    """
    await _check_project_access(session, context, req.project_id)
    title = req.title or _shorten_ai_name(req.question)

    resolver = await _resolve_action_sources(
        session, context,
        project_id=req.project_id,
        question=req.question,
        intent="recommended_query",
        card_context=req.card_context,
    )

    try:
        ai_result = await _generate_sql_for_question(
            session, context, req.project_id, req.question,
            preferred_sources=resolver.preferred_sources,
            relevant_columns=resolver.relevant_columns,
        )
    except ai.AIUnavailableError as exc:
        if exc.declined:
            friendly, details = _ai_generation_error(exc.detail)
            return {
                "title": title,
                "description": req.description or "",
                "sql": "",
                "columns": [],
                "rows": [],
                "suggestedVisualization": {"type": "table"},
                "dataSourcesUsed": [],
                "explanation": "",
                "status": "generation_error",
                "error": friendly,
                "errorDetails": details,
            }
        return {
            "title": title,
            "description": req.description or "",
            "sql": "",
            "columns": [],
            "rows": [],
            "suggestedVisualization": {"type": "table"},
            "dataSourcesUsed": [],
            "explanation": "",
            "status": "ai_unavailable",
            "error": "The AI service is currently unavailable. Please try again shortly.",
            "errorDetails": {"aiError": str(exc)},
        }
    except HTTPException as exc:
        friendly, details = _ai_generation_error(exc.detail)
        return {
            "title": title,
            "description": req.description or "",
            "sql": "",
            "columns": [],
            "rows": [],
            "suggestedVisualization": {"type": "table"},
            "dataSourcesUsed": [],
            "explanation": "",
            "status": "generation_error",
            "error": friendly,
            "errorDetails": details,
        }

    allowed_tables = ai_result.pop("_allowed_tables", [])
    sql = (ai_result.get("sql") or "").strip().rstrip(";")
    if not sql or not _is_read_only_select(sql):
        return {
            "title": title,
            "description": req.description or "",
            "sql": sql if sql else "",
            "columns": [],
            "rows": [],
            "suggestedVisualization": {"type": "table"},
            "dataSourcesUsed": [],
            "explanation": ai_result.get("explanation", ""),
            "status": "generation_error",
            "error": "We could not safely build a query for this recommendation.",
            "errorDetails": {"sql": sql} if sql else {},
        }

    table_schema = await _project_table_schema(
        session, tenant_id=context.tenant_id, project_id=req.project_id
    )
    result, sql, exec_error = await _execute_with_repair(
        session, context,
        project_id=req.project_id,
        sql=sql,
        allowed_tables=allowed_tables,
        max_rows=req.max_rows,
        table_schema=table_schema,
    )
    if result is None:
        return {
            "title": title,
            "description": req.description or "",
            "sql": sql,
            "columns": [],
            "rows": [],
            "suggestedVisualization": {"type": "table"},
            "dataSourcesUsed": [_detect_datasource(sql, allowed_tables) or ""],
            "explanation": ai_result.get("explanation", ""),
            "status": "execution_error",
            "error": "We could not run this query against the project's data.",
            "errorDetails": {
                "sql": sql,
                "executionError": exec_error,
            },
        }

    columns = result.get("columns", [])
    rows = result.get("rows", [])[: req.max_rows]
    used = _detect_datasource(sql, allowed_tables)
    response: dict[str, Any] = {
        "title": title,
        "description": req.description or "",
        "sql": sql,
        "columns": columns,
        "rows": rows,
        "suggestedVisualization": _suggest_visualization(columns, rows),
        "dataSourcesUsed": [used] if used else [],
        "explanation": ai_result.get("explanation", ""),
        "status": "success",
        "error": None,
    }
    # M4 fast-follow: an executed preview is a structured result — stamp the
    # shared ResponseEnvelope so the modal renders via the same ResponsePresenter
    # as ask-and-run. Additive/fail-closed (same helper as ask-and-run).
    await _attach_ask_analytics(
        response, session, tenant_id=context.tenant_id, question=req.question
    )
    _attach_presentation(response)
    return response


async def _attach_ask_analytics(
    response: dict[str, Any],
    session: AsyncSession,
    *,
    tenant_id: int | None,
    question: str,
) -> None:
    """Run the governed Analytical Method Engine over a chat answer.

    Chat answers previously carried no analytical provenance while insight cards
    did, so the same data got a statistical read on a card and none in
    conversation. Running the engine here gives chat R-first execution (the
    catalog's methods are ``execution_engine: r``, with Python fallback) plus the
    method envelope the R Analytics badge and Explain panel already render.

    Fail-closed: any problem leaves the answer exactly as it was.
    """
    try:
        if get_engine_mode() == EngineMode.OFF:
            return
        columns = response.get("columns") or []
        rows = response.get("rows") or []
        if not columns or not rows:
            return
        envelope = await analyze_methods(
            session,
            tenant_id=tenant_id,
            columns=columns,
            rows=rows,
            question=question,
        )
        if envelope and envelope.get("method") is not None:
            response["analyticalMethod"] = envelope
            response["method_envelope"] = envelope
    except Exception as exc:  # pragma: no cover - analytics must never break chat
        logger.warning("ask analytics skipped: %s", exc)
