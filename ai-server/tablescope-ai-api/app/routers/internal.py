"""Internal endpoints for platform-api driven offline operations.

These endpoints are HMAC-signed and only reachable from the trusted app server.
They expose vector-store maintenance and conversion primitives that the app
server itself does not have the toolchain to perform.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.core.security import verify_signature
from app.services import vector_store

logger = logging.getLogger(__name__)

router = APIRouter()


class ReindexRequest(BaseModel):
    tenant_id: int
    source_collection: str
    target_collection: str
    embedding_model: str
    embedding_dim: int
    signature: str = ""
    timestamp: float = 0.0


class ReindexResponse(BaseModel):
    status: str
    points_total: int = 0
    points_indexed: int = 0
    recall_score: float | None = None
    detail: str | None = None


class DeleteTenantCollectionRequest(BaseModel):
    tenant_id: int
    signature: str = ""
    timestamp: float = 0.0


class DeleteProjectVectorsRequest(BaseModel):
    tenant_id: int
    project_id: int
    signature: str = ""
    timestamp: float = 0.0


class DeleteVectorsResponse(BaseModel):
    status: str
    detail: str | None = None


@router.post("/vector-store/reindex", response_model=ReindexResponse)
async def reindex_tenant_collection(req: ReindexRequest) -> ReindexResponse:
    """Re-embed all vectors from a source collection into a new target collection.

    This is Phase 5 of the LLM Framework: swapping an embedding model requires a
    dual-collection re-index and recall comparison before cut-over. The caller
    (platform-api) decides whether the recall score is high enough to alias the
    target collection as the active tenant collection.
    """
    payload = req.model_dump(exclude={"signature"}, exclude_unset=True)
    verify_signature(payload, req.signature)

    try:
        result = await vector_store.reindex_collection(
            source=req.source_collection,
            target=req.target_collection,
            embedding_model=req.embedding_model,
            embedding_dim=req.embedding_dim,
        )
    except vector_store.VectorStoreError as exc:
        logger.exception("Reindex failed for %s", req.source_collection)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    return ReindexResponse(**result)


@router.post("/vector-store/delete-tenant-collection", response_model=DeleteVectorsResponse)
async def delete_tenant_collection(req: DeleteTenantCollectionRequest) -> DeleteVectorsResponse:
    """Drop a tenant's entire Qdrant collection (TS-ISO-011: cross-store deletion).

    Called by platform-api's tenant-deletion flow as a best-effort cleanup
    step alongside the Postgres row purge and VDB undeploy.
    """
    payload = req.model_dump(exclude={"signature"}, exclude_unset=True)
    verify_signature(payload, req.signature)

    try:
        await vector_store.delete_tenant_collection(req.tenant_id)
    except vector_store.VectorStoreError as exc:
        logger.exception(
            "Failed to delete Qdrant collection for tenant %s", req.tenant_id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    return DeleteVectorsResponse(status="ok")


@router.post("/vector-store/delete-project-vectors", response_model=DeleteVectorsResponse)
async def delete_project_vectors(req: DeleteProjectVectorsRequest) -> DeleteVectorsResponse:
    """Delete one project's vectors from its tenant's collection (TS-ISO-011).

    Called by platform-api's project-deletion flow as a best-effort cleanup
    step.
    """
    payload = req.model_dump(exclude={"signature"}, exclude_unset=True)
    verify_signature(payload, req.signature)

    try:
        await vector_store.delete_project_vectors(req.tenant_id, req.project_id)
    except vector_store.VectorStoreError as exc:
        logger.exception(
            "Failed to delete Qdrant vectors for tenant %s project %s",
            req.tenant_id,
            req.project_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    return DeleteVectorsResponse(status="ok")
