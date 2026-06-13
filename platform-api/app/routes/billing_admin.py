"""Admin tools for provisioning requests (Phase 13). Super-admin only."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.billing import TenantProvisioningRequest
from app.models.user import User
from app.schemas.billing import ProvisioningStatusResponse
from app.services.tenant_onboarding_service import TenantOnboardingService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/provisioning", tags=["admin"])


async def _require_super_admin(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> RequestContext:
    if context.is_service:
        return context
    user = await session.get(User, context.user_id)
    if user is None or not user.is_super_admin:
        raise HTTPException(status_code=403, detail="Super-admin required")
    return context


@router.get("", response_model=list[ProvisioningStatusResponse])
async def list_requests(
    session: AsyncSession = Depends(get_db),
    _: RequestContext = Depends(_require_super_admin),
) -> list[ProvisioningStatusResponse]:
    rows = (
        await session.scalars(
            select(TenantProvisioningRequest).order_by(
                TenantProvisioningRequest.id.desc()
            )
        )
    ).all()
    return [ProvisioningStatusResponse.model_validate(r) for r in rows]


@router.get("/{request_id}", response_model=ProvisioningStatusResponse)
async def get_request(
    request_id: int,
    session: AsyncSession = Depends(get_db),
    _: RequestContext = Depends(_require_super_admin),
) -> ProvisioningStatusResponse:
    req = await session.get(TenantProvisioningRequest, request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="Not found")
    return ProvisioningStatusResponse.model_validate(req)


@router.post("/{request_id}/retry", response_model=ProvisioningStatusResponse)
async def retry_request(
    request_id: int,
    session: AsyncSession = Depends(get_db),
    _: RequestContext = Depends(_require_super_admin),
) -> ProvisioningStatusResponse:
    req = await session.get(TenantProvisioningRequest, request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="Not found")
    if req.status not in ("failed", "manual_review", "payment_confirmed", "provisioning"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot retry from status {req.status!r}",
        )
    # Reset to payment_confirmed so the orchestrator re-runs the tier automation.
    req.status = "payment_confirmed"
    await session.flush()
    onboarding = TenantOnboardingService(session)
    await onboarding.provision_from_stripe_activation(req.id)
    await session.refresh(req)
    return ProvisioningStatusResponse.model_validate(req)


@router.post("/{request_id}/cancel", response_model=ProvisioningStatusResponse)
async def cancel_request(
    request_id: int,
    session: AsyncSession = Depends(get_db),
    _: RequestContext = Depends(_require_super_admin),
) -> ProvisioningStatusResponse:
    req = await session.get(TenantProvisioningRequest, request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="Not found")
    if req.status == "provisioned":
        raise HTTPException(status_code=409, detail="Already provisioned")
    req.status = "cancelled"
    await session.flush()
    return ProvisioningStatusResponse.model_validate(req)
