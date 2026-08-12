
from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.services.llm_framework import resolve_active_routing_for_capability

from .transport import _chat_sem, _post

_CAPABILITY_BY_PATH: dict[str, str | None] = {
    "/ai/intelligence/plan": "dashboard_planning",
    "/ai/intelligence/project-insight": "insight_interpretation",
    "/ai/intelligence/knowledge-graph": "insight_interpretation",
    "/ai/intelligence/conversation-turn": "general_reasoning",
    "/ai/intelligence/select-insight-card": "insight_interpretation",
    "/ai/intelligence/fix-sql": "sql_generation",
    "/ai/intelligence/interpret": "insight_interpretation",
    "/ai/query/generate": "sql_generation",
    "/ai/actions/draft": "general_reasoning",
    "/ai/ask": "general_reasoning",
    "/ai/grounding/search": None,
}


async def _post_with_model(
    path: str,
    payload: dict[str, Any],
    *,
    capability: str | None = None,
    **kwargs: Any,
) -> dict[str, Any] | None:
    """Wrap _post and inject the active LLM model for the call's capability."""
    if capability is None:
        capability = _CAPABILITY_BY_PATH.get(path)
    if capability:
        routing = await resolve_active_routing_for_capability(capability)
        payload = {
            **payload,
            "model": routing.model,
            "ollama_url": routing.ollama_url,
            "routing_version": routing.version,
            "capability": capability,
        }
    return await _post(path, payload, **kwargs)


async def plan(
    *,
    tenant_id: int,
    user_id: int,
    project_id: int,
    allowed_tables: list[str],
    documents: list[dict[str, Any]],
    table_schema: list[dict[str, Any]] | None = None,
    relationship_hints: list[dict[str, Any]] | None = None,
    max_analyses: int = 6,
    granularity: int = 3,
    project_context: dict[str, Any] | None = None,
    knowledge_graph_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]] | None:
    """Ask the LLM to propose diagnostic analyses. Returns ``analyses`` or None."""
    settings = get_settings()
    max_retries = max(0, settings.home_intelligence_plan_max_retries)
    result = await _post_with_model(
        "/ai/intelligence/plan",
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "project_id": project_id,
            "allowed_tables": allowed_tables,
            "table_schema": table_schema or [],
            "documents": documents,
            "relationship_hints": relationship_hints or [],
            "reference_kpis": [],
            "max_analyses": max_analyses,
            "granularity": granularity,
            "project_context": project_context or {},
            "knowledge_graph_context": knowledge_graph_context or {},
        },
        max_attempts=max_retries + 1,
        retry_read_timeouts=True,
        retry_base_seconds=max(
            0.0, settings.home_intelligence_plan_retry_base_seconds
        ),
    )
    if result is None:
        return None
    analyses = result.get("analyses")
    return analyses if isinstance(analyses, list) else []


async def project_insight(
    *,
    tenant_id: int,
    user_id: int,
    project_id: int,
    project: dict[str, Any],
    tables: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    queries: list[dict[str, Any]],
    dashboards: list[dict[str, Any]],
    kpis: list[str],
    knowledge_graph_context: dict[str, Any] | None = None,
    recent_activity: dict[str, Any] | None = None,
    project_context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Ask the AI server for the project-scoped Project Insight report.

    Returns the structured contract (executiveSummary, questionsToAsk,
    trendDetection, recommendedDashboards/Queries/Kpis,
    insightValidationWorkflow), or ``None`` if the AI server is unavailable so
    the caller can degrade gracefully.
    """
    result = await _post_with_model(
        "/ai/intelligence/project-insight",
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "project_id": project_id,
            "project": project,
            "tables": tables,
            "documents": documents,
            "queries": queries,
            "dashboards": dashboards,
            "kpis": kpis,
            "knowledge_graph_context": knowledge_graph_context or {},
            "recent_activity": recent_activity or {},
            "project_context": project_context or {},
        },
    )
    return result if isinstance(result, dict) else None


async def knowledge_graph_cards(
    *,
    tenant_id: int,
    user_id: int,
    project_id: int,
    lens: str,
    center: dict[str, Any],
    neighbors: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    kpis: list[str],
    max_cards: int = 8,
) -> list[dict[str, Any]] | None:
    """Ask the LLM for Knowledge-Graph insight cards for the selected node.

    Returns the raw card dicts, or ``None`` when the AI server is unavailable so
    the caller can fall back to the deterministic cards.
    """
    result = await _post_with_model(
        "/ai/intelligence/knowledge-graph",
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "project_id": project_id,
            "lens": lens,
            "center": center,
            "neighbors": neighbors,
            "documents": documents,
            "kpis": kpis,
            "max_cards": max_cards,
        },
    )
    if result is None:
        return None
    cards = result.get("cards")
    return cards if isinstance(cards, list) else []


async def classify_conversation_turn(
    *,
    tenant_id: int,
    user_id: int,
    project_id: int,
    message: str,
    has_prior_result: bool = False,
    prior_sql: str = "",
    result_columns: list[str] | None = None,
    numeric_columns: list[str] | None = None,
    categorical_columns: list[str] | None = None,
    row_count: int = 0,
    current_chart: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Ask the LLM to classify a conversational-analytics turn.

    Returns ``{"intent": ..., "chart": {...}, "data_question": ..., "confidence": ..., "reason": ...}``
    or ``None`` when AI is disabled, so the caller can fall back to its
    deterministic degraded path.
    """
    result = await _post_with_model(
        "/ai/intelligence/conversation-turn",
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "project_id": project_id,
            "message": message,
            "has_prior_result": has_prior_result,
            "prior_sql": prior_sql,
            "result_columns": result_columns or [],
            "numeric_columns": numeric_columns or [],
            "categorical_columns": categorical_columns or [],
            "row_count": row_count,
            "current_chart": current_chart or {},
        },
    )
    if not isinstance(result, dict) or not result.get("intent"):
        return None
    return result


async def select_matching_insight_card(
    *,
    tenant_id: int,
    user_id: int,
    project_id: int,
    question: str,
    candidates: list[dict[str, str]],
) -> dict[str, Any] | None:
    """Ask the LLM which candidate Insight Card, if any, answers ``question``.

    ``candidates`` is ``[{"insight_id": ..., "title": ..., "summary": ...}, ...]``
    -- cards the caller has already resolved to be authorized and within the
    project scope being searched. Returns
    ``{"insight_id": ... | None, "confidence": ..., "reason": ...}`` or
    ``None`` when AI is disabled, so the caller can fall back to declining
    the match rather than guessing.
    """
    result = await _post_with_model(
        "/ai/intelligence/select-insight-card",
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "project_id": project_id,
            "question": question,
            "candidates": candidates,
        },
    )
    if not isinstance(result, dict):
        return None
    return result


async def fix_sql(
    *,
    tenant_id: int,
    user_id: int,
    project_id: int,
    sql: str,
    error: str,
    allowed_tables: list[str],
    table_schema: list[dict[str, Any]] | None = None,
) -> str | None:
    """Ask the LLM to repair a query that the engine rejected.

    Returns a corrected SQL string, or None if the AI is unavailable or
    declines to fix it.
    """
    result = await _post_with_model(
        "/ai/intelligence/fix-sql",
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "project_id": project_id,
            "sql": sql,
            "error": error,
            "allowed_tables": allowed_tables,
            "table_schema": table_schema or [],
        },
    )
    if result is None:
        return None
    fixed = result.get("sql")
    return fixed if isinstance(fixed, str) and fixed.strip() else None


async def interpret(
    *,
    tenant_id: int,
    user_id: int,
    project_id: int,
    analyses: list[dict[str, Any]],
    project_context: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]] | None:
    """Turn executed results into prose. Returns ``{analysis_id: insight}`` or None."""
    if not analyses:
        return {}
    result = await _post_with_model(
        "/ai/intelligence/interpret",
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "project_id": project_id,
            "analyses": analyses,
            "project_context": project_context or {},
        },
    )
    if result is None:
        return None
    out: dict[str, dict[str, Any]] = {}
    for ins in result.get("insights", []):
        if isinstance(ins, dict) and ins.get("id"):
            out[str(ins["id"])] = ins
    return out


async def generate_sql(
    *,
    tenant_id: int,
    user_id: int,
    project_id: int,
    prompt: str,
    allowed_tables: list[str],
    source_catalog: list[dict[str, Any]] | None = None,
    preferred_sources: list[str] | None = None,
    relevant_columns: list[str] | None = None,
    knowledge_graph_context: dict[str, Any] | None = None,
    grounding_evidence: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Generate SQL for a natural-language question.

    Routed through the same signed, retry-aware client as plan/interpret calls.
    Bounded concurrency prevents KG-precache traffic from starving chat answers.
    Returns ``None`` when the AI service is disabled or unreachable.
    """
    async with _chat_sem():
        return await _post_with_model(
            "/ai/query/generate",
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "project_id": project_id,
                "prompt": prompt,
                "allowed_tables": allowed_tables,
                "source_catalog": source_catalog or [],
                "preferred_sources": preferred_sources or [],
                "relevant_columns": relevant_columns or [],
                "knowledge_graph_context": knowledge_graph_context or {},
                "grounding_evidence": grounding_evidence,
            },
        )


async def generate_action_draft(
    *,
    tenant_id: int,
    user_id: int,
    project_id: int,
    insight: dict[str, Any],
) -> dict[str, Any] | None:
    """Generate a structured action draft (title, description, subtasks, success criteria).

    Returns ``None`` when the AI service is disabled or unreachable.
    """
    return await _post_with_model(
        "/ai/actions/draft",
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "project_id": project_id,
            "insight_type": insight.get("insight_type", "insight"),
            "title": insight.get("title", ""),
            "summary": insight.get("summary", ""),
            "recommended_action": insight.get("recommended_action", ""),
            "severity": insight.get("severity", "info"),
            "sources": insight.get("sources", {}),
            "supporting_sources": insight.get("supporting_sources", []),
            "explanation": insight.get("explanation"),
        },
    )


async def search_grounding_vectors(
    *,
    tenant_id: int,
    user_id: int,
    project_id: int,
    question: str,
    scope: str = "project",
    limit: int = 12,
) -> dict[str, Any] | None:
    """Query the AI server for vector-grounded passages (project + reference)."""
    result = await _post_with_model(
        "/ai/grounding/search",
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "project_id": project_id,
            "question": question,
            "scope": scope,
            "limit": limit,
        },
    )
    return result if isinstance(result, dict) else None


async def ask(
    *,
    tenant_id: int,
    user_id: int,
    project_id: int,
    question: str,
    scope: str = "project",
    include_query_history: bool = True,
    include_dashboard_context: bool = True,
    history: list[dict[str, Any]] | None = None,
    knowledge_graph_context: dict[str, Any] | None = None,
    grounding_evidence: dict[str, Any] | None = None,
    data_result: dict[str, Any] | None = None,
    matched_insights: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Free-text answer or synthesized data/insight summary from the AI server.

    When ``data_result`` is provided the LLM synthesizes the final answer from
    the executed query result. When ``matched_insights`` is provided it answers
    from the grounded insight card analysis. Both can be supplied together.
    """
    async with _chat_sem():
        return await _post_with_model(
            "/ai/ask",
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "project_id": project_id,
                "question": question,
                "scope": scope,
                "include_query_history": include_query_history,
                "include_dashboard_context": include_dashboard_context,
                "history": history or [],
                "knowledge_graph_context": knowledge_graph_context or {},
                "grounding_evidence": grounding_evidence,
                "data_result": data_result,
                "matched_insights": matched_insights,
            },
        )
