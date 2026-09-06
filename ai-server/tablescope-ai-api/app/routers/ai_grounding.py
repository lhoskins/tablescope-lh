"""Proactive grounding vector search endpoint.

Called by the platform-api grounding orchestrator so platform-api can merge
vector, lexical, knowledge-graph, and governed-KPI evidence before sending the
final grounding package back to the SQL-generation and ask endpoints.
"""

import logging
import uuid

from fastapi import APIRouter, HTTPException, status

from app.core.activity import update_activity
from app.core.security import verify_signature
from app.models.schemas import (
    GroundingPassage,
    GroundingSearchRequest,
    GroundingSearchResponse,
)
from app.services import context_builder, llm_client, vector_store
from app.services.context_builder import ContextBuildError

logger = logging.getLogger(__name__)
router = APIRouter()


def _to_passage(point: dict, *, source_type: str, tier: str = "") -> GroundingPassage:
    payload = point.get("payload") or {}
    return GroundingPassage(
        id=str(point.get("id", "")),
        document_id=payload.get("document_id") or payload.get("source_id"),
        chunk_index=payload.get("chunk_index"),
        title=payload.get("title") or "",
        text=payload.get("chunk_text") or "",
        tier=payload.get("tier") or tier,
        source_type=source_type,
        retrieval_score=float(point.get("score") or 0.0),
        retrieval_method="vector",
    )


@router.post("/grounding/search", response_model=GroundingSearchResponse)
async def grounding_search(req: GroundingSearchRequest) -> GroundingSearchResponse:
    """Embed a question and return the most relevant project + reference passages."""
    request_id = str(uuid.uuid4())
    verify_signature(req.model_dump(exclude={"signature"}, exclude_unset=True), req.signature)

    try:
        permissions = await context_builder._verify_permissions(
            req.tenant_id, req.user_id, req.project_id
        )
        vector_access = context_builder.resolve_vector_access(
            permissions,
            tenant_id=req.tenant_id,
            user_id=req.user_id,
            project_id=req.project_id,
        )
    except ContextBuildError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vector retrieval is not authorized",
        ) from exc

    query_embedding = await llm_client.generate_embedding(req.question)

    project_passages: list[GroundingPassage] = []
    try:
        results = await vector_store.search_vectors(
            access=vector_access,
            query_vector=query_embedding,
            limit=req.limit,
        )
        project_passages = [_to_passage(r, source_type="project_asset") for r in results]
    except Exception as exc:
        logger.warning("Grounding project vector search failed: %s", exc)

    reference_passages: list[GroundingPassage] = []
    try:
        results = await vector_store.search_reference_vectors(
            access=vector_access,
            query_vector=query_embedding,
            limit=max(3, req.limit // 2),
        )
        reference_passages = [_to_passage(r, source_type="reference_library") for r in results]
    except Exception as exc:
        logger.warning("Grounding reference vector search failed: %s", exc)

    update_activity(req.user_id, req.tenant_id, req.project_id)

    return GroundingSearchResponse(
        request_id=request_id,
        project_passages=project_passages,
        reference_passages=reference_passages,
    )
