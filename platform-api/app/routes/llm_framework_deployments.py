"""LLM Framework deployment routes — approve, activate, rollback and listing."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import require_human_platform_admin, require_platform_admin
from app.config import get_settings
from app.database import get_db
from app.routes.llm_framework_inventory import _require_enabled
from app.schemas.llm_framework import (
    ActivateRequest,
    ActivateResponse,
    ApproveDeploymentResponse,
    DeploymentSummary,
    RollbackResponse,
)
from app.services.llm_deployment import (
    DeploymentError,
    activate_deployment,
    approve_deployment,
    rollback_deployment,
)
from app.services.llm_framework import (
    list_deployments,
    record_llm_audit_event,
    validate_routing_capability,
)

router = APIRouter(prefix="/llm-framework", tags=["llm-framework"])


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
    await record_llm_audit_event(
        session,
        actor_user_id=context.user_id,
        action="approve",
        entity_type="deployment",
        entity_id=deployment.id,
        details={"status": deployment.status},
    )
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
    await record_llm_audit_event(
        session,
        actor_user_id=context.user_id,
        action="activate",
        entity_type="deployment",
        entity_id=deployment.id,
        details={"capability": capability, "target_id": request.target_id},
    )
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
    context: RequestContext = Depends(require_human_platform_admin),
) -> dict[str, Any]:
    _require_enabled()
    try:
        deployment = await rollback_deployment(session, deployment_id)
    except DeploymentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await record_llm_audit_event(
        session,
        actor_user_id=context.user_id,
        action="rollback",
        entity_type="deployment",
        entity_id=deployment.id,
        details={},
    )
    await session.commit()
    return {"deployment_id": deployment.id, "status": deployment.status}


@router.get("/deployments", response_model=list[DeploymentSummary])
async def list_llm_deployments(
    limit: int = 50,
    session: AsyncSession = Depends(get_db),
    _: RequestContext = Depends(require_platform_admin),
) -> Any:
    _require_enabled()
    return await list_deployments(session, limit=limit)
