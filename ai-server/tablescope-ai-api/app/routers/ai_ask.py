"""The ``/ai/ask`` endpoint."""

import logging
import uuid

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


@router.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest) -> AskResponse:
    """Ask Tablescope AI a question about the active project."""
    request_id = str(uuid.uuid4())

    # 1. Verify signature
    verify_signature(req.model_dump(exclude={"signature"}), req.signature)

    # 2. Build permission-aware context
    try:
        ctx = await context_builder.build_context(
            tenant_id=req.tenant_id,
            user_id=req.user_id,
            project_id=req.project_id,
            scope=req.scope,
            question=req.question,
            feature="ask",
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
    prompt = f"{context_text}\n\n{history_text}User question: {req.question}"

    answer = await llm_client.generate(
        prompt=prompt,
        system_prompt=SYSTEM_PROMPT,
        model=settings.reasoning_model,
    )

    # 4. Update activity
    update_activity(req.user_id, req.tenant_id, req.project_id)

    # 5. Log
    logger.info(
        "AI ask | request_id=%s tenant=%d project=%d user=%d",
        request_id, req.tenant_id, req.project_id, req.user_id,
    )

    return AskResponse(
        answer=answer,
        model_used=settings.reasoning_model,
        request_id=request_id,
        context_summary={
            "metadata_count": len(ctx.allowed_context.get("metadata", [])),
            "document_count": len(ctx.allowed_context.get("documents", [])),
            "project_document_count": len(
                ctx.allowed_context.get("project_documents", [])
            ),
            "query_count": len(ctx.allowed_context.get("queries", [])),
        },
    )
