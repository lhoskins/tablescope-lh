"""LLM Framework artifact lifecycle routes — staging, preflight, install, reindex."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import require_human_platform_admin, require_platform_admin
from app.config import get_settings
from app.database import get_db
from app.models.llm_framework import LLMEmbeddingMigration
from app.routes.llm_framework_inventory import _require_catalog_enabled, _require_enabled
from app.schemas.llm_framework import (
    EmbeddingMigrationSummary,
    InstallRequest,
    InstallResponse,
    ModelArtifactDetail,
    PreflightResponse,
    QuarantineReleaseResponse,
    ReindexRequest,
    ReindexResponse,
    StageArtifactRequest,
    StageArtifactResponse,
)
from app.services.llm_deployment import DeploymentError, preflight_install
from app.services.llm_embedding_migration import EmbeddingMigrationError, start_embedding_migration
from app.services.llm_framework import (
    create_artifact_and_stage,
    enqueue_deploy_llm_artifact,
    enqueue_stage_llm_artifact,
    get_artifact,
    record_llm_audit_event,
    release_quarantined_artifact,
)

router = APIRouter(prefix="/llm-framework", tags=["llm-framework"])


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
    await record_llm_audit_event(
        session,
        actor_user_id=context.user_id,
        action="stage_artifact",
        entity_type="artifact",
        entity_id=artifact.id,
        details={"repo_url": request.repo_url, "quantization": request.quantization},
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
    await record_llm_audit_event(
        session,
        actor_user_id=context.user_id,
        action="quarantine_release",
        entity_type="artifact",
        entity_id=artifact.id,
        details={"previous_status": "quarantined", "status": artifact.status},
    )
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
    await record_llm_audit_event(
        session,
        actor_user_id=context.user_id,
        action="install",
        entity_type="artifact",
        entity_id=artifact_id,
        details={"target_id": request.target_id, "job_id": job_id},
    )
    return {
        "installation_id": 0,
        "deployment_id": 0,
        "status": "queued",
        "job_id": job_id,
    }


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
