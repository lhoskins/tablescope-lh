"""LLM Framework administration routes.

Phase 1 is read-only inventory plus lightweight artifact lifecycle helpers.
No model downloads, conversion, or activation happen here.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import require_human_platform_admin, require_platform_admin
from app.config import get_settings
from app.database import get_db
from app.schemas.llm_framework import (
    CapabilitiesResponse,
    InventoryResponse,
    ModelArtifactDetail,
    QuarantineReleaseResponse,
)
from app.services.llm_framework import (
    CAPABILITIES,
    get_artifact,
    get_inventory,
    release_quarantined_artifact,
)

router = APIRouter(prefix="/llm-framework", tags=["llm-framework"])


def _require_enabled() -> None:
    if not get_settings().llm_framework_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM Framework is disabled",
        )


class FrameworkStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    enabled: bool
    gguf_only: bool
    deployment_enabled: bool
    two_person_approval_required: bool
    auto_rollback_enabled: bool
    manifest_signing_key_fingerprint: str


@router.get("/status", response_model=FrameworkStatusResponse)
async def get_llm_framework_status(
    _: RequestContext = Depends(require_platform_admin),
) -> dict[str, Any]:
    settings = get_settings()
    return {
        "enabled": settings.llm_framework_enabled,
        "gguf_only": settings.llm_model_catalog_gguf_only,
        "deployment_enabled": settings.llm_deployment_enabled,
        "two_person_approval_required": settings.llm_two_person_approval_required,
        "auto_rollback_enabled": settings.llm_auto_rollback_enabled,
        "manifest_signing_key_fingerprint": settings.llm_manifest_signing_key_fingerprint,
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
    _: RequestContext = Depends(require_human_platform_admin),
) -> dict[str, Any]:
    _require_enabled()
    artifact = await release_quarantined_artifact(session, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return {
        "artifact_id": artifact.id,
        "previous_status": "quarantined",
        "status": artifact.status,
    }
