"""Provisioning status (public, session-scoped) + VPN onboarding intake."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.billing import TenantProvisioningRequest
from app.schemas.billing import (
    ProvisioningStatusResponse,
    VpnIntakeRequest,
    VpnIntakeResponse,
)
from app.services import billing_audit as audit
from app.services.aws_vpn_provisioning_service import VpnProvisioningError
from app.services.tenant_provisioning_service import (
    TenantNotFound,
    TenantProvisioningService,
    VpnMetadata,
)
from app.tasks.workflows import enqueue_provision_tenant_vpn

logger = logging.getLogger(__name__)
router = APIRouter(tags=["provisioning"])


@router.get("/provisioning/status", response_model=ProvisioningStatusResponse)
async def provisioning_status(
    session_id: str = Query(..., description="Stripe checkout session id"),
    session: AsyncSession = Depends(get_db),
) -> ProvisioningStatusResponse:
    """Public: a checkout session id acts as a capability token for its status."""
    req = await session.scalar(
        select(TenantProvisioningRequest).where(
            TenantProvisioningRequest.stripe_checkout_session_id == session_id
        )
    )
    if req is None:
        raise HTTPException(status_code=404, detail="No provisioning request for session")
    return ProvisioningStatusResponse.model_validate(req)


@router.post("/tenant/vpn/intake", response_model=VpnIntakeResponse)
async def vpn_intake(
    payload: VpnIntakeRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> VpnIntakeResponse:
    """Collect customer VPN network details AFTER login (Phase 9)."""
    req = await session.scalar(
        select(TenantProvisioningRequest).where(
            TenantProvisioningRequest.tenant_id == context.tenant_id,
            TenantProvisioningRequest.requires_vpn.is_(True),
        )
    )
    if req is None:
        raise HTTPException(status_code=404, detail="No VPN provisioning request for tenant")

    # Persist the intake metadata and routing choice immediately.
    provisioner = TenantProvisioningService(session)
    try:
        await provisioner.attach_vpn_metadata(
            req.tenant_slug,
            VpnMetadata(routing_type=payload.routing),
        )
    except TenantNotFound:
        logger.warning("data plane not found for tenant slug %s", req.tenant_slug)

    req.vpn_status = "configuring"
    await session.flush()
    audit.audit(
        audit.VPN_INTAKE_RECEIVED,
        tenant_id=context.tenant_id,
        provisioning_request_id=req.id,
        routing=payload.routing,
        ike_version=payload.ike_version,
        cidr_count=len(payload.customer_cidr_ranges),
    )

    # Enqueue AWS-side VPC, Customer Gateway and Site-to-Site VPN provisioning.
    try:
        await enqueue_provision_tenant_vpn(
            tenant_id=req.tenant_slug,
            customer_gateway_ip=payload.public_endpoint,
            customer_onprem_cidrs=payload.customer_cidr_ranges,
            routing_type=payload.routing,
        )
        req.vpn_status = "configuring"
        await session.flush()
        return VpnIntakeResponse(
            vpn_status="configuring",
            message="AWS VPN provisioning started. The workspace status page will update when the connection is ready.",
        )
    except VpnProvisioningError as exc:
        logger.error("VPN provisioning failed for tenant %s: %s", req.tenant_slug, exc)
        req.vpn_status = "failed"
        req.error_message = str(exc)[:500]
        await session.flush()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
