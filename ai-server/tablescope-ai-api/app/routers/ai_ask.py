"""The ``/ai/ask`` endpoint."""

import logging
import re
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.core.activity import update_activity
from app.core.config import settings
from app.core.security import verify_signature
from app.models.schemas import (
    AskRequest,
    AskResponse,
)
from app.services import context_builder, llm_client
from app.services.context_builder import ContextBuildError
from app.services.kg_context import format_knowledge_graph_context

from .ai_shared import (
    SYSTEM_PROMPT,
    _format_conversation_history,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _fit_context(text: str, max_model_len: int = 12288, max_tokens: int = 512) -> str:
    """Truncate context so prompt + max_tokens stays under vLLM max_model_len."""
    # Approx 3.5 chars per token; reserve tokens for system prompt, question,
    # answer and overhead.
    reserve_tokens = max_tokens + 120
    char_budget = max(0, (max_model_len - reserve_tokens) * 3)
    if len(text) <= char_budget:
        return text
    return text[:char_budget].rstrip() + "\n\n[context truncated for length]"


def _format_data_result(question: str, data: dict[str, Any]) -> str:
    """Render an executed query result as a grounded block for the LLM."""
    lines: list[str] = ["LIVE QUERY RESULT", f"User question: {question}", ""]

    sql = data.get("sql") or data.get("query")
    if sql:
        lines.append(f"SQL: {sql}")

    columns = data.get("columns") or []
    rows = data.get("rows") or []
    row_count = data.get("rowCount") or len(rows)
    truncated = data.get("truncated")
    if columns:
        lines.append(f"Columns: {', '.join(str(c) for c in columns)}")
    if row_count:
        lines.append(f"Row count: {row_count}{' (truncated)' if truncated else ''}")

    if rows:
        lines.append("Rows:")
        for row in rows[:20]:
            if isinstance(row, dict):
                lines.append(
                    "  - " + ", ".join(f"{k}={v}" for k, v in row.items())
                )
            else:
                lines.append(f"  - {row}")

    viz = data.get("suggestedVisualization") or data.get("chart_config") or {}
    if viz.get("type"):
        lines.append(f"Suggested chart: {viz['type']}")
        if viz.get("xField"):
            lines.append(f"  x: {viz['xField']}")
        if viz.get("yField"):
            lines.append(f"  y: {viz['yField']}")
        if viz.get("y2Field"):
            lines.append(f"  y2: {viz['y2Field']}")

    return "\n".join(lines)


def _format_matched_insights(question: str, insights: list[dict[str, Any]]) -> str:
    """Render matched insight card(s) as a grounded block for the LLM."""
    lines: list[str] = ["MATCHED INSIGHT CARD ANALYSIS", f"User question: {question}", ""]
    for idx, insight in enumerate(insights[:6], 1):
        title = insight.get("title") or "Untitled"
        project = insight.get("projectName") or f"project {insight.get('projectId')}"
        lines.append(f"{idx}. {title} ({project})")
        if insight.get("summary"):
            lines.append(f"   Summary: {insight['summary'][:400]}")
        if insight.get("card_type") or insight.get("type"):
            lines.append(f"   Type: {insight.get('card_type') or insight.get('type')}")
        chart = insight.get("chart") or {}
        if chart.get("type"):
            lines.append(f"   Chart: {chart['type']}")
        if insight.get("series"):
            lines.append(f"   Series: {', '.join(str(s) for s in insight['series'])}")
        if insight.get("trend"):
            lines.append(f"   Trend: {insight['trend']}")
        if insight.get("diagnostics"):
            lines.append("   Diagnostics:")
            for d in insight["diagnostics"][:5]:
                if isinstance(d, dict):
                    lines.append(f"      - {d.get('title', '')}: {d.get('detail', '')}")
                else:
                    lines.append(f"      - {d}")
        if insight.get("proposedActions"):
            lines.append("   Proposed actions:")
            for a in insight["proposedActions"][:5]:
                if isinstance(a, dict):
                    lines.append(f"      - {a.get('title', '')}: {a.get('detail', '')}")
                else:
                    lines.append(f"      - {a}")
        if insight.get("result_preview"):
            lines.append(f"   Recorded values:\n{insight['result_preview']}")
        if insight.get("sql"):
            lines.append(f"   SQL:\n```sql\n{insight['sql'][:500]}\n```")
        lines.append("")
    return "\n".join(lines)


@router.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest) -> AskResponse:
    """Ask Tablescope AI a question about the active project."""
    request_id = str(uuid.uuid4())

    # 1. Verify signature
    verify_signature(req.model_dump(exclude={"signature"}, exclude_unset=True), req.signature)

    # 2. Synthesize an answer from a live query result and/or matched insight
    # card(s) when the app has already done the analytical work. Otherwise fall
    # through to the normal document/KG-grounded prose path.
    grounded_block = ""
    if req.data_result:
        grounded_block = _format_data_result(req.question, req.data_result)
    if req.matched_insights:
        insight_block = _format_matched_insights(req.question, req.matched_insights)
        grounded_block = f"{grounded_block}\n\n{insight_block}".strip()

    ctx = None
    context_text = ""
    history_text = _format_conversation_history(req.history)
    if not grounded_block:
        # Build permission-aware context only when we need the document/KG
        # grounding. Data-driven questions already carry their own result.
        try:
            ctx = await context_builder.build_context(
                tenant_id=req.tenant_id,
                user_id=req.user_id,
                project_id=req.project_id,
                scope=req.scope,
                question=req.question,
                feature="ask",
                grounding_evidence=req.grounding_evidence,
            )
        except ContextBuildError as e:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: {e.reason}",
            )
        context_text = context_builder.context_to_prompt_text(ctx)
        # Fold in the Knowledge Graph context so prose answers cite validated
        # risks/gaps/measured KPIs surfaced by the graph (not Reference Library docs).
        kg_block = format_knowledge_graph_context(req.knowledge_graph_context)
        if kg_block:
            context_text = f"{context_text}\n\n{kg_block}"
        # Prose contexts can be large; reserve token room for the answer and
        # system prompt so the request fits within the vLLM max_model_len window.
        context_text = _fit_context(context_text, max_tokens=1536)

    if grounded_block:
        # Synthesizing an answer from an already-executed query result needs very
        # little context. Keep the prompt tiny so it fits comfortably on a small
        # GPU/CPU context window and the model stays concise.
        prompt = (
            f"{grounded_block}\n\n"
            f"User question: {req.question}\n\n"
            "Answer the question in one or two sentences using the live result "
            "above. Cite specific numbers. Do not show reasoning or SQL."
        )
        answer_system_prompt = (
            "You are a concise data assistant. Answer using only the provided result. "
            "Never show chain-of-thought or reasoning. Do not repeat the prompt."
        )
        answer_max_tokens = 512
        answer_stop = None
    else:
        prompt = (
            f"{context_text}\n\n{history_text}"
            f"User question: {req.question}\n\n"
            "Answer from the Reference Library documents, Knowledge Graph, and "
            "project context above. If the question asks for a list of documents, "
            "return a concise list with each document title, its domain tag, and a one-line summary. "
            "If the question names a domain (e.g. IT, ESG, Finance), only include documents "
            "whose domain_tag matches that domain. If it asks about a specific document, "
            "answer from that document's summary and cite its title. Do not invent data or SQL "
            "that is not shown. Keep the answer concise and conversational."
        )
        answer_system_prompt = SYSTEM_PROMPT
        answer_max_tokens = 1536
        answer_stop = None



    answer = await llm_client.generate(
        prompt=prompt,
        system_prompt=answer_system_prompt,
        model=req.model or settings.reasoning_model,
        ollama_url=req.ollama_url,
        max_tokens=answer_max_tokens,
        stop=answer_stop,
    )

    # Some models emit a "to=self" artifact or leading whitespace; strip it.
    answer = re.sub(r"^(to=self\s*)+", "", answer).strip()

    # 4. Update activity
    update_activity(req.user_id, req.tenant_id, req.project_id)

    # 5. Log
    logger.info(
        "AI ask | request_id=%s tenant=%d project=%d user=%d",
        request_id, req.tenant_id, req.project_id, req.user_id,
    )

    grounding_manifest: dict[str, Any] | None = None
    if req.grounding_evidence:
        grounding_manifest = {
            "question": req.grounding_evidence.question,
            "passage_count": len(req.grounding_evidence.passages),
            "kg_node_count": len(req.grounding_evidence.kg_nodes),
            "kpi_count": len(req.grounding_evidence.kpis),
            "retrieved_at": req.grounding_evidence.retrieved_at.isoformat(),
        }

    allowed_context = ctx.allowed_context if ctx else {}
    return AskResponse(
        answer=answer,
        model_used=req.model or settings.reasoning_model,
        request_id=request_id,
        context_summary={
            "metadata_count": len(allowed_context.get("metadata", [])),
            "document_count": len(allowed_context.get("documents", [])),
            "project_document_count": len(
                allowed_context.get("project_documents", [])
            ),
            "query_count": len(allowed_context.get("queries", [])),
        },
        grounding_manifest=grounding_manifest,
    )
