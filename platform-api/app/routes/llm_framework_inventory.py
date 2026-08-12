"""LLM Framework inventory, runtime targets, routing and audit routes.

Read-only inventory plus runtime-target registration and routing-profile
administration. Also hosts the feature-flag guards shared by the sibling
llm-framework route modules.
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
from app.models.llm_framework import LLMRuntimeTarget
from app.schemas.llm_framework import (
    AuditEventSummary,
    CapabilitiesResponse,
    InventoryResponse,
    RoutingProfileRequest,
    RoutingProfileResponse,
    RuntimeTargetCreate,
    RuntimeTargetSummary,
)
from app.services.llm_framework import (
    CAPABILITIES,
    DuplicateRuntimeTargetError,
    InvalidCapabilityError,
    get_inventory,
    record_llm_audit_event,
    register_runtime_target,
    upsert_routing_profile,
)

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
    dynamic_routing_enabled: bool
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
        "dynamic_routing_enabled": settings.llm_dynamic_routing_enabled,
        "embedding_recall_threshold": settings.llm_embedding_recall_threshold,
    }


@router.get("/targets", response_model=list[RuntimeTargetSummary])
async def list_llm_runtime_targets(
    session: AsyncSession = Depends(get_db),
    _: RequestContext = Depends(require_platform_admin),
) -> Any:
    """Return all authorized runtime targets with capacity and assignment metadata."""
    _require_enabled()
    targets = (await session.scalars(select(LLMRuntimeTarget).order_by(LLMRuntimeTarget.name))).all()
    return targets


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


@router.post("/runtime-targets", response_model=RuntimeTargetSummary, status_code=201)
async def create_llm_runtime_target(
    request: RuntimeTargetCreate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_human_platform_admin),
) -> Any:
    _require_enabled()
    try:
        target = await register_runtime_target(
            session,
            name=request.name,
            host=request.host,
            runtime_type=request.runtime_type,
            version=request.version,
            max_loaded_models=request.max_loaded_models,
            keep_alive_minutes=request.keep_alive_minutes,
            environment=request.environment,
            gpu_memory_gb=request.gpu_memory_gb,
            system_ram_gb=request.system_ram_gb,
            disk_gb=request.disk_gb,
            is_internet_isolated=request.is_internet_isolated,
            max_concurrency=request.max_concurrency,
            context_tokens=request.context_tokens,
            labels=request.labels,
        )
    except DuplicateRuntimeTargetError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await record_llm_audit_event(
        session,
        actor_user_id=context.user_id,
        action="register_target",
        entity_type="runtime_target",
        entity_id=target.id,
        details={"host": request.host, "runtime_type": request.runtime_type},
    )
    return target


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


@router.get("/audit-events", response_model=list[AuditEventSummary])
async def list_llm_audit_events(
    limit: int = 50,
    session: AsyncSession = Depends(get_db),
    _: RequestContext = Depends(require_platform_admin),
) -> Any:
    _require_enabled()
    from app.models.llm_framework import LLMAuditEvent

    events = (
        await session.scalars(
            select(LLMAuditEvent).order_by(LLMAuditEvent.created_at.desc()).limit(min(limit, 200))
        )
    ).all()
    return events


@router.put("/routing", response_model=RoutingProfileResponse)
async def upsert_llm_routing_profile(
    request: RoutingProfileRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_human_platform_admin),
) -> Any:
    _require_enabled()
    settings = get_settings()
    if not settings.llm_dynamic_routing_enabled:
        raise HTTPException(status_code=503, detail="Dynamic routing is disabled")
    try:
        profile = await upsert_routing_profile(
            session,
            capability=request.capability,
            target_id=request.target_id,
            installation_id=request.installation_id,
            deployment_id=request.deployment_id,
            priority=request.priority,
            is_active=request.is_active,
            expected_version=request.expected_version,
        )
    except (ValueError, InvalidCapabilityError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await record_llm_audit_event(
        session,
        actor_user_id=context.user_id,
        action="upsert_routing_profile",
        entity_type="routing_profile",
        entity_id=profile.id,
        details={
            "capability": profile.capability,
            "target_id": profile.target_id,
            "installation_id": profile.installation_id,
            "is_active": profile.is_active,
        },
    )
    await session.commit()
    return profile
