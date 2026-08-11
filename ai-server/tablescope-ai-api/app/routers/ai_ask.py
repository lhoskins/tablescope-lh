"""The ``/ai/ask`` endpoint."""

import logging
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

    # 2. Build permission-aware context
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

    # 3. Send ONLY allowed context to LLM
    context_text = context_builder.context_to_prompt_text(ctx)
    # Fold in the Knowledge Graph context so prose answers cite validated
    # risks/gaps/measured KPIs surfaced by the graph (not Reference Library docs).
    kg_block = format_knowledge_graph_context(req.knowledge_graph_context)
    if kg_block:
        context_text = f"{context_text}\n\n{kg_block}"
    history_text = _format_conversation_history(req.history)

    # Synthesize an answer from a live query result and/or matched insight card(s)
    # when the app has already done the analytical work. Otherwise fall through
    # to the normal document/KG-grounded prose path.
    grounded_block = ""
    if req.data_result:
        grounded_block = _format_data_result(req.question, req.data_result)
    if req.matched_insights:
        insight_block = _format_matched_insights(req.question, req.matched_insights)
        grounded_block = f"{grounded_block}\n\n{insight_block}".strip()

    if grounded_block:
        prompt = (
            f"{context_text}\n\n{grounded_block}\n\n"
            f"{history_text}"
            f"User question: {req.question}\n\n"
            "Ground your answer in the live query result and/or matched insight "
            "card analysis above. Cite specific numbers, trends, and chart series. "
            "If a live result is present, use it as the primary source; use matched "
            "insight cards only when they directly address the question's subject. "
            "You may also use Reference Library documents, KG findings, and other "
            "context above as supporting material. Do not invent data or SQL that "
            "is not shown. Keep the answer concise and conversational."
        )
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

    answer = await llm_client.generate(
        prompt=prompt,
        system_prompt=SYSTEM_PROMPT,
        model=req.model or settings.reasoning_model,
    )

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

    return AskResponse(
        answer=answer,
        model_used=req.model or settings.reasoning_model,
        request_id=request_id,
        context_summary={
            "metadata_count": len(ctx.allowed_context.get("metadata", [])),
            "document_count": len(ctx.allowed_context.get("documents", [])),
            "project_document_count": len(
                ctx.allowed_context.get("project_documents", [])
            ),
            "query_count": len(ctx.allowed_context.get("queries", [])),
        },
        grounding_manifest=grounding_manifest,
    )
