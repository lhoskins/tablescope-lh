"""LLM Framework Hugging Face catalog routes — search, detail and conversion."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import require_human_platform_admin, require_platform_admin
from app.config import get_settings
from app.database import get_db
from app.models.llm_framework import LLMModelConversion
from app.routes.llm_framework_inventory import _require_catalog_enabled, _require_enabled
from app.schemas.llm_framework import (
    CatalogDetail,
    CatalogSearchResult,
    ConvertRequest,
    ConvertResponse,
    ModelConversionSummary,
)
from app.services.llm_framework import get_catalog_detail, search_catalog
from app.services.llm_model_conversion import ModelConversionError, create_source_artifact_and_convert

router = APIRouter(prefix="/llm-framework", tags=["llm-framework"])


@router.get("/catalog/search", response_model=list[CatalogSearchResult])
async def search_llm_catalog(
    q: str,
    limit: int = 20,
    _: RequestContext = Depends(require_platform_admin),
) -> list[CatalogSearchResult]:
    _require_catalog_enabled()
    models = await search_catalog(q, limit=min(limit, 50))
    return [
        CatalogSearchResult(
            repo_id=m.repo_id,
            publisher=m.publisher,
            name=m.name,
            tags=m.tags,
            license=m.license,
            description=m.description,
            downloads=m.downloads,
            likes=m.likes,
            last_modified=m.last_modified,
            gguf_files=[
                {"filename": f.filename, "size": f.size, "lfs": f.lfs}
                for f in m.gguf_files
            ],
            gguf_total_bytes=sum((f.size or 0) for f in m.gguf_files) or None,
        )
        for m in models
    ]


@router.get("/catalog/detail", response_model=CatalogDetail)
async def get_llm_catalog_detail(
    repo_url: str,
    _: RequestContext = Depends(require_platform_admin),
) -> CatalogDetail:
    _require_catalog_enabled()
    m = await get_catalog_detail(repo_url)
    return CatalogDetail(
        repo_id=m.repo_id,
        publisher=m.publisher,
        name=m.name,
        commit_sha=m.commit_sha,
        tags=m.tags,
        license=m.license,
        description=m.description,
        downloads=m.downloads,
        likes=m.likes,
        last_modified=m.last_modified,
        license_url=m.license_url,
        gguf_files=[
            {"filename": f.filename, "size": f.size, "lfs": f.lfs}
            for f in m.gguf_files
        ],
        siblings=[
            {"filename": f.filename, "size": f.size, "lfs": f.lfs}
            for f in m.siblings
        ],
        gguf_total_bytes=sum((f.size or 0) for f in m.gguf_files) or None,
    )


@router.post("/catalog/convert", response_model=ConvertResponse, status_code=202)
async def convert_fp16_catalog_entry(
    request: ConvertRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_human_platform_admin),
) -> dict[str, Any]:
    """Start an FP16 / safetensors -> GGUF conversion from a Hugging Face repo."""
    _require_enabled()
    settings = get_settings()
    if not settings.llm_fp16_conversion_enabled:
        raise HTTPException(status_code=503, detail="FP16 conversion is disabled")

    try:
        artifact, conversion, job_id = await create_source_artifact_and_convert(
            session,
            repo_url=request.repo_url,
            quantization=request.quantization,
            requested_by_user_id=context.user_id,
        )
    except ModelConversionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    return {
        "source_artifact_id": artifact.id,
        "conversion_id": conversion.id,
        "status": conversion.status,
        "job_id": job_id,
    }


@router.get("/model-conversions", response_model=list[ModelConversionSummary])
async def list_model_conversions(
    session: AsyncSession = Depends(get_db),
    _: RequestContext = Depends(require_platform_admin),
) -> list[Any]:
    """List all FP16 -> GGUF conversions."""
    _require_enabled()
    result = await session.scalars(select(LLMModelConversion).order_by(LLMModelConversion.created_at.desc()))
    return list(result.all())
