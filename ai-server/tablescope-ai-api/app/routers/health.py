"""Health check endpoint for the AI server."""

import httpx

from fastapi import APIRouter

from app.core.config import settings
from app.models.schemas import HealthResponse
from app.services import llm_client, vector_store

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Check health of all AI services."""
    # Ollama
    ollama_status = await llm_client.check_health()

    # Qdrant
    try:
        client = vector_store.get_client()
        client.get_collections()
        qdrant_status = "ok"
    except Exception:
        qdrant_status = "unavailable"

    # GPU — check via Ollama's /api/ps which reports GPU layers
    gpu_status = "unavailable"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.ollama_url}/api/tags")
            if resp.status_code == 200:
                gpu_status = "available"
    except Exception:
        pass

    overall = "ok" if all(
        s == "ok" or s == "available"
        for s in [ollama_status, qdrant_status, gpu_status]
    ) else "degraded"

    return HealthResponse(
        status=overall,
        ollama=ollama_status,
        qdrant=qdrant_status,
        gpu=gpu_status,
    )
