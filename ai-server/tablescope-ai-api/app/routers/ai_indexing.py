"""Vector indexing endpoints for documents and reference-library assets."""

import logging
import uuid

from fastapi import APIRouter

from app.core.activity import update_activity
from app.core.config import settings
from app.core.security import verify_signature
from app.models.schemas import (
    IndexDocumentRequest,
    IndexReferenceRequest,
)
from app.services import llm_client, vector_store

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/index/document")
async def index_document(req: IndexDocumentRequest) -> dict:
    """Index a project document into the tenant's vector collection."""
    request_id = str(uuid.uuid4())
    verify_signature(req.model_dump(exclude={"signature"}, exclude_unset=True), req.signature)

    # Ensure tenant collection exists
    await vector_store.ensure_collection(req.tenant_id)

    # Chunk the content
    content = req.content
    if not content:
        return {"status": "no_content", "request_id": request_id}

    # Simple chunking (512 char chunks with 50 char overlap)
    chunk_size = 512
    overlap = 50
    chunks: list[str] = []
    for i in range(0, len(content), chunk_size - overlap):
        chunk = content[i:i + chunk_size]
        if chunk.strip():
            chunks.append(chunk)

    if not chunks:
        return {"status": "no_chunks", "request_id": request_id}

    # Generate embeddings
    embeddings = await llm_client.generate_embeddings(chunks)

    # Build payloads with security fields
    payloads = []
    for idx, chunk in enumerate(chunks):
        payloads.append({
            "tenant_id": req.tenant_id,
            "project_id": req.project_id,
            "document_id": req.document_id,
            "chunk_id": f"chunk_{idx:04d}",
            "chunk_index": idx,
            "chunk_text": chunk,
            "visibility": req.visibility,
            "owner_user_id": req.user_id,
            "source_type": req.source_type,
            "source_id": req.source_id,
            "embedding_model": settings.embedding_model,
        })

    # Upsert into tenant-specific collection
    point_ids = await vector_store.upsert_vectors(
        tenant_id=req.tenant_id,
        vectors=embeddings,
        payloads=payloads,
    )

    update_activity(req.user_id, req.tenant_id, req.project_id)

    logger.info(
        "Indexed document %d: %d chunks | tenant=%d project=%d",
        req.document_id, len(chunks), req.tenant_id, req.project_id,
    )

    return {
        "status": "indexed",
        "document_id": req.document_id,
        "chunks_indexed": len(chunks),
        "vector_ids": point_ids,
        "request_id": request_id,
    }


@router.post("/index/reference")
async def index_reference(req: IndexReferenceRequest) -> dict:
    """Index a reference-library document into the shared, tier-scoped store.

    Reference docs are governed knowledge (industry/company/project tier) made
    available to the AI assistant and Home planner across projects. Re-indexing
    is idempotent: existing chunks for the document are dropped first.
    """
    request_id = str(uuid.uuid4())
    verify_signature(req.model_dump(exclude={"signature"}, exclude_unset=True), req.signature)

    await vector_store.delete_reference_document(req.document_id)

    content = req.content
    if not content.strip():
        return {"status": "no_content", "request_id": request_id}

    # Simple chunking (512 char chunks with 50 char overlap) — mirrors documents.
    chunk_size = 512
    overlap = 50
    chunks: list[str] = []
    for i in range(0, len(content), chunk_size - overlap):
        chunk = content[i:i + chunk_size]
        if chunk.strip():
            chunks.append(chunk)

    if not chunks:
        return {"status": "no_chunks", "request_id": request_id}

    embeddings = await llm_client.generate_embeddings(chunks)

    payloads = []
    for idx, chunk in enumerate(chunks):
        payloads.append({
            "tier": req.tier,
            "tenant_id": req.tenant_id,
            "project_id": req.project_id,
            "document_id": req.document_id,
            "title": req.title,
            "chunk_id": f"chunk_{idx:04d}",
            "chunk_index": idx,
            "chunk_text": chunk,
            "source_type": "reference_library",
            "embedding_model": settings.embedding_model,
        })

    point_ids = await vector_store.upsert_reference_vectors(
        vectors=embeddings,
        payloads=payloads,
    )

    logger.info(
        "Indexed reference document %d (%s): %d chunks",
        req.document_id, req.tier, len(chunks),
    )

    return {
        "status": "indexed",
        "document_id": req.document_id,
        "chunks_indexed": len(chunks),
        "vector_ids": point_ids,
        "request_id": request_id,
    }
