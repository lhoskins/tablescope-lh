"""LLM Framework administration routes.

Phase 1 is read-only inventory plus lightweight artifact lifecycle helpers.
Phase 2 adds Hugging Face catalog search and staged artifact download.
No model activation happens here.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import require_human_platform_admin, require_platform_admin
from app.config import get_settings
from app.database import get_db
from app.models.llm_framework import LLMEmbeddingMigration, LLMModelConversion
from app.schemas.llm_framework import (
    ActivateRequest,
    ActivateResponse,
    ApproveDeploymentResponse,
    CapabilitiesResponse,
    CatalogDetail,
    CatalogSearchResult,
    ConvertRequest,
    ConvertResponse,
    EmbeddingMigrationSummary,
    InstallRequest,
    InstallResponse,
    InventoryResponse,
    ModelArtifactDetail,
    ModelConversionSummary,
    PreflightResponse,
    QuarantineReleaseResponse,
    ReindexRequest,
    ReindexResponse,
    RollbackResponse,
    StageArtifactRequest,
    StageArtifactResponse,
)
from app.services.llm_deployment import (
    DeploymentError,
    activate_deployment,
    approve_deployment,
    preflight_install,
    rollback_deployment,
)
from app.services.llm_embedding_migration import EmbeddingMigrationError, start_embedding_migration
from app.services.llm_framework import (
    CAPABILITIES,
    create_artifact_and_stage,
    enqueue_deploy_llm_artifact,
    enqueue_stage_llm_artifact,
    get_artifact,
    get_catalog_detail,
    get_inventory,
    release_quarantined_artifact,
    search_catalog,
    validate_routing_capability,
)
from app.services.llm_model_conversion import ModelConversionError, create_source_artifact_and_convert

router = APIRouter(prefix="/llm-framework", tags=["llm-framework"])


def _require_enabled() -> None:
    if not get_settings().llm_framework_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM Framework is disabled",
        )


def _require_catalog_enabled() -> None:
    _require_enabled()
    if not get_settings().llm_framework_hf_catalog_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM Framework catalog is disabled",
        )


class FrameworkStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    enabled: bool
    hf_catalog_enabled: bool
    gguf_only: bool
    deployment_enabled: bool
    two_person_approval_required: bool
    auto_rollback_enabled: bool
    manifest_signing_key_fingerprint: str
    embedding_migration_enabled: bool
    fp16_conversion_enabled: bool
    embedding_recall_threshold: float


@router.get("/status", response_model=FrameworkStatusResponse)
async def get_llm_framework_status(
    _: RequestContext = Depends(require_platform_admin),
) -> dict[str, Any]:
    settings = get_settings()
    return {
        "enabled": settings.llm_framework_enabled,
        "hf_catalog_enabled": settings.llm_framework_hf_catalog_enabled,
        "gguf_only": settings.llm_model_catalog_gguf_only,
        "deployment_enabled": settings.llm_deployment_enabled,
        "two_person_approval_required": settings.llm_two_person_approval_required,
        "auto_rollback_enabled": settings.llm_auto_rollback_enabled,
        "manifest_signing_key_fingerprint": settings.llm_manifest_signing_key_fingerprint,
        "embedding_migration_enabled": settings.llm_embedding_migration_enabled,
        "fp16_conversion_enabled": settings.llm_fp16_conversion_enabled,
        "embedding_recall_threshold": settings.llm_embedding_recall_threshold,
    }


@router.get("/inventory", response_model=InventoryResponse)
async def get_llm_inventory(
    session: AsyncSession = Depends(get_db),
    _: RequestContext = Depends(require_platform_admin),
) -> dict[str, Any]:
    _require_enabled()
    inventory = await get_inventory(session)
    return {
        "targets": inventory["targets"],
        "artifacts": inventory["artifacts"],
        "installations": inventory["installations"],
        "routing_profiles": inventory["routing_profiles"],
    }


@router.get("/capabilities", response_model=CapabilitiesResponse)
async def get_llm_capabilities(
    _: RequestContext = Depends(require_platform_admin),
) -> dict[str, Any]:
    _require_enabled()
    settings = get_settings()
    return {
        "capabilities": CAPABILITIES,
        "gguf_only": settings.llm_model_catalog_gguf_only,
        "deployment_enabled": settings.llm_deployment_enabled,
    }


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


@router.post("/artifacts/stage", response_model=StageArtifactResponse, status_code=202)
async def stage_llm_artifact_from_catalog(
    request: StageArtifactRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_human_platform_admin),
) -> dict[str, Any]:
    _require_catalog_enabled()
    artifact, job_id = await create_artifact_and_stage(
        session,
        repo_url=request.repo_url,
        quantization=request.quantization,
        name=request.name,
        requested_by_user_id=context.user_id,
    )
    return {"artifact_id": artifact.id, "job_id": job_id, "status": artifact.status}


@router.get("/artifacts/{artifact_id}", response_model=ModelArtifactDetail)
async def get_llm_artifact_detail(
    artifact_id: int,
    session: AsyncSession = Depends(get_db),
    _: RequestContext = Depends(require_platform_admin),
) -> Any:
    _require_enabled()
    artifact = await get_artifact(session, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return artifact


@router.post("/artifacts/{artifact_id}/quarantine-release", response_model=QuarantineReleaseResponse)
async def release_quarantined_llm_artifact(
    artifact_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_human_platform_admin),
) -> dict[str, Any]:
    _require_enabled()
    artifact = await release_quarantined_artifact(session, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    # Re-queue the staging worker so the artifact is re-verified.
    await enqueue_stage_llm_artifact(artifact.id, context.user_id)
    return {
        "artifact_id": artifact.id,
        "previous_status": "quarantined",
        "status": artifact.status,
    }


@router.post("/artifacts/{artifact_id}/preflight", response_model=PreflightResponse)
async def run_llm_preflight(
    artifact_id: int,
    request: InstallRequest,
    session: AsyncSession = Depends(get_db),
    _: RequestContext = Depends(require_platform_admin),
) -> dict[str, Any]:
    _require_enabled()
    try:
        report = await preflight_install(session, artifact_id=artifact_id, target_id=request.target_id)
    except DeploymentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "artifact_id": artifact_id,
        "target_id": request.target_id,
        "target_reachable": report.target_reachable,
        "disk_ok": report.disk_ok,
        "slot_ok": report.slot_ok,
        "detail": report.detail,
    }


@router.post("/artifacts/{artifact_id}/install", response_model=InstallResponse, status_code=202)
async def install_llm_artifact(
    artifact_id: int,
    request: InstallRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_human_platform_admin),
) -> dict[str, Any]:
    _require_enabled()
    settings = get_settings()
    if not settings.llm_deployment_enabled:
        raise HTTPException(status_code=503, detail="LLM deployment is disabled")
    artifact = await get_artifact(session, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if artifact.status != "verified":
        raise HTTPException(status_code=400, detail="Artifact is not verified")
    job_id = await enqueue_deploy_llm_artifact(
        artifact_id=artifact_id,
        target_id=request.target_id,
        requested_by_user_id=context.user_id,
    )
    return {
        "installation_id": 0,
        "deployment_id": 0,
        "status": "queued",
        "job_id": job_id,
    }


@router.post("/deployments/{deployment_id}/approve", response_model=ApproveDeploymentResponse)
async def approve_llm_deployment(
    deployment_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_human_platform_admin),
) -> dict[str, Any]:
    _require_enabled()
    try:
        deployment = await approve_deployment(session, deployment_id, context.user_id)
    except DeploymentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    return {"deployment_id": deployment.id, "status": deployment.status}


@router.post("/deployments/{deployment_id}/activate", response_model=ActivateResponse)
async def activate_llm_deployment(
    deployment_id: int,
    request: ActivateRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_human_platform_admin),
) -> dict[str, Any]:
    _require_enabled()
    settings = get_settings()
    if not settings.llm_dynamic_routing_enabled:
        raise HTTPException(status_code=503, detail="Dynamic routing is disabled")
    try:
        capability = await validate_routing_capability(request.capability)
        deployment = await activate_deployment(
            session,
            deployment_id=deployment_id,
            capability=capability,
            target_id=request.target_id,
        )
    except DeploymentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    return {
        "deployment_id": deployment.id,
        "status": deployment.status,
        "capability": capability,
        "target_id": request.target_id,
    }


@router.post("/deployments/{deployment_id}/rollback", response_model=RollbackResponse)
async def rollback_llm_deployment(
    deployment_id: int,
    session: AsyncSession = Depends(get_db),
    _: RequestContext = Depends(require_human_platform_admin),
) -> dict[str, Any]:
    _require_enabled()
    try:
        deployment = await rollback_deployment(session, deployment_id)
    except DeploymentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    return {"deployment_id": deployment.id, "status": deployment.status}


@router.post("/artifacts/{artifact_id}/reindex", response_model=ReindexResponse, status_code=202)
async def reindex_llm_artifact(
    artifact_id: int,
    request: ReindexRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_human_platform_admin),
) -> dict[str, Any]:
    """Start an embedding-model re-index migration for one tenant."""
    _require_enabled()
    settings = get_settings()
    if not settings.llm_embedding_migration_enabled:
        raise HTTPException(status_code=503, detail="Embedding migration is disabled")

    try:
        migration = await start_embedding_migration(
            session,
            artifact_id=artifact_id,
            tenant_id=request.tenant_id,
            embedding_model=request.embedding_model,
            embedding_dim=request.embedding_dim,
            requested_by_user_id=context.user_id,
        )
    except EmbeddingMigrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    from app.tasks.workflows import enqueue_reindex_embedding_model
    job_id = await enqueue_reindex_embedding_model(migration.id, context.user_id)
    await session.commit()
    return {
        "migration_id": migration.id,
        "status": migration.status,
        "job_id": job_id,
    }


@router.get("/embedding-migrations", response_model=list[EmbeddingMigrationSummary])
async def list_embedding_migrations(
    session: AsyncSession = Depends(get_db),
    _: RequestContext = Depends(require_platform_admin),
) -> list[Any]:
    """List all embedding re-index migrations."""
    _require_enabled()
    result = await session.scalars(select(LLMEmbeddingMigration).order_by(LLMEmbeddingMigration.created_at.desc()))
    return list(result.all())


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
