"""Tenant data-plane networking artifacts.

Renders the host firewall script and the tenant's Docker Compose, attaches
VPN/VPC metadata (e.g. from Terraform outputs), reports health and produces the
customer VPN onboarding package.

All endpoints require super-admin.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.config import get_settings
from app.database import get_db
from app.models.shared_vdb import SharedVDB
from app.routes.tenant_data_planes_crud import _provision_vdbs_for_tenant, _read, _require_super_admin
from app.schemas.tenant_data_plane import (
    ComposePreview,
    FirewallScriptPreview,
    HealthCheckRequest,
    OnboardingPackage,
    ProvisionContainerResponse,
    StorageMetadataIn,
    TenantDataPlaneRead,
    VpnMetadataIn,
)
from app.services.tenant_firewall_service import (
    FIREWALL_CONFIG_DIR,
    SYSTEMD_UNIT_PATH,
    TenantFirewallService,
)
from app.services.tenant_health_service import TenantHealthService
from app.services.tenant_provisioning_service import (
    StorageMetadata,
    TenantNotFound,
    TenantProvisioningService,
    VpnMetadata,
)
from app.services.tenant_storage_resolver import StorageIsolationError
from app.services.vdb_management import VDBProvisioningError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tenant-data-planes", tags=["tenant-data-planes"])


@router.get("/firewall-script", response_model=FirewallScriptPreview)
async def get_firewall_script(
    session: AsyncSession = Depends(get_db),
    _: RequestContext = Depends(_require_super_admin),
) -> FirewallScriptPreview:
    svc = TenantProvisioningService(session)
    script = await svc.render_firewall_script()
    return FirewallScriptPreview(
        script=script,
        config_dir=FIREWALL_CONFIG_DIR,
        systemd_unit_path=SYSTEMD_UNIT_PATH,
        systemd_unit=TenantFirewallService().render_systemd_unit(),
    )


@router.post("/{tenant_id}/vpn-metadata", response_model=TenantDataPlaneRead)
async def attach_vpn_metadata(
    tenant_id: str,
    payload: VpnMetadataIn,
    session: AsyncSession = Depends(get_db),
    _: RequestContext = Depends(_require_super_admin),
) -> TenantDataPlaneRead:
    svc = TenantProvisioningService(session)
    try:
        plane = await svc.attach_vpn_metadata(tenant_id, VpnMetadata(**payload.model_dump()))
    except TenantNotFound as exc:
        raise HTTPException(status_code=404, detail="Tenant data plane not found") from exc
    await session.commit()
    await session.refresh(plane)
    return _read(plane)


@router.post("/{tenant_id}/storage-metadata", response_model=TenantDataPlaneRead)
async def attach_storage_metadata(
    tenant_id: str,
    payload: StorageMetadataIn,
    session: AsyncSession = Depends(get_db),
    _: RequestContext = Depends(_require_super_admin),
) -> TenantDataPlaneRead:
    """Import the non-secret private-S3 outputs created by Terraform."""
    if payload.s3_bucket_name == get_settings().s3_bucket_name:
        raise HTTPException(status_code=422, detail="An isolated data plane cannot use the shared S3 bucket")
    svc = TenantProvisioningService(session)
    try:
        plane = await svc.attach_storage_metadata(
            tenant_id, StorageMetadata(**payload.model_dump())
        )
        await session.commit()
    except TenantNotFound as exc:
        raise HTTPException(status_code=404, detail="Tenant data plane not found") from exc
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="The bucket, access point, endpoint, KMS key, or IAM role is already bound to another tenant.",
        ) from exc
    await session.refresh(plane)
    return _read(plane)


@router.post("/{tenant_id}/provision-vdbs", response_model=TenantDataPlaneRead)
async def provision_vdbs(
    tenant_id: str,
    session: AsyncSession = Depends(get_db),
    _: RequestContext = Depends(_require_super_admin),
) -> TenantDataPlaneRead:
    """Provision VDBs only after the private storage probe has passed."""
    svc = TenantProvisioningService(session)
    try:
        plane = await svc.get(tenant_id)
    except TenantNotFound as exc:
        raise HTTPException(status_code=404, detail="Tenant data plane not found") from exc
    if plane.org_tenant_id is None:
        raise HTTPException(status_code=409, detail="Bind an application tenant first")
    if plane.storage_status != "ready":
        raise HTTPException(status_code=409, detail="Private storage must validate before VDB provisioning")
    if plane.status not in ("infrastructure_ready", "active"):
        raise HTTPException(
            status_code=409,
            detail="Container, firewall, VDB path, and private storage health must pass first",
        )
    existing = await session.scalar(
        select(SharedVDB).where(SharedVDB.tenant_id == plane.org_tenant_id)
    )
    if existing is None:
        try:
            await _provision_vdbs_for_tenant(
                session,
                org_tenant_id=plane.org_tenant_id,
                user_id=None,
                strict=True,
            )
        except (StorageIsolationError, VDBProvisioningError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    plane.status = "active"
    await session.commit()
    await session.refresh(plane)
    return _read(plane)


@router.get("/{tenant_id}/compose", response_model=ComposePreview)
async def preview_compose(
    tenant_id: str,
    session: AsyncSession = Depends(get_db),
    _: RequestContext = Depends(_require_super_admin),
) -> ComposePreview:
    svc = TenantProvisioningService(session)
    try:
        plane = await svc.get(tenant_id)
    except TenantNotFound as exc:
        raise HTTPException(status_code=404, detail="Tenant data plane not found") from exc
    return ComposePreview(
        tenant_id=plane.tenant_id,
        compose_path=svc.layout_for(plane).compose_host_path,
        compose_content=svc.render_compose(plane),
    )


@router.post("/{tenant_id}/provision-container", response_model=ProvisionContainerResponse)
async def provision_container(
    tenant_id: str,
    session: AsyncSession = Depends(get_db),
    _: RequestContext = Depends(_require_super_admin),
) -> ProvisionContainerResponse:
    svc = TenantProvisioningService(session)
    try:
        plane = await svc.get(tenant_id)
    except TenantNotFound as exc:
        raise HTTPException(status_code=404, detail="Tenant data plane not found") from exc

    layout = svc.layout_for(plane)
    from app.services.tenant_compose_service import TenantComposeService

    generated = TenantComposeService().generate(layout, write=False, plane=plane)
    plane.status = "container_pending"
    await session.commit()
    return ProvisionContainerResponse(
        tenant_id=plane.tenant_id,
        compose_path=generated.compose_path,
        compose_content=generated.content,
        directories=generated.directories,
        note=(
            "Compose + directory layout rendered. Apply on the EC2 host: create the "
            "directories, write the compose file, set the tenant Teiid API key env var, "
            "then `docker compose -f <file> up -d`. Run the firewall script afterwards. "
            "Finally connect the control plane to this tenant's network so the "
            "(containerized) platform API can reach the tenant Teiid over the tenant "
            f"network: `docker network connect {layout.docker_network_name} "
            "tablescope-platform-api-1` (and the -worker-1 container)."
        ),
    )


@router.post("/{tenant_id}/health")
async def health_check(
    tenant_id: str,
    payload: HealthCheckRequest | None = None,
    session: AsyncSession = Depends(get_db),
    _: RequestContext = Depends(_require_super_admin),
) -> dict:
    svc = TenantProvisioningService(session)
    try:
        plane = await svc.get(tenant_id)
    except TenantNotFound as exc:
        raise HTTPException(status_code=404, detail="Tenant data plane not found") from exc

    targets = payload.connectivity_targets if payload else []
    report = await TenantHealthService().check(plane, connectivity_targets=targets)
    plane.last_health_status = report.teiid_status
    plane.vpn_status = report.vpn_status
    plane.storage_status = report.storage_status
    if report.storage_status == "ready":
        plane.storage_validated_at = datetime.now(UTC)
    else:
        plane.storage_validated_at = None
        if plane.status in ("active", "infrastructure_ready"):
            plane.status = "storage_failed"
    plane.last_health_message = report.messages.get("storage")
    # Infrastructure health alone is not enough to activate the tenant. VDB
    # provisioning is a separate, explicit step after storage validation.
    if (
        plane.status in ("provisioning", "container_pending", "storage_failed")
        and report.teiid_status == "healthy"
        and report.firewall_status == "applied"
        and report.vdb_path_status == "ok"
        and report.storage_status == "ready"
    ):
        plane.status = "infrastructure_ready"
    await session.commit()
    return report.to_dict()


@router.get("/{tenant_id}/onboarding-package", response_model=OnboardingPackage)
async def onboarding_package(
    tenant_id: str,
    session: AsyncSession = Depends(get_db),
    _: RequestContext = Depends(_require_super_admin),
) -> OnboardingPackage:
    svc = TenantProvisioningService(session)
    try:
        plane = await svc.get(tenant_id)
    except TenantNotFound as exc:
        raise HTTPException(status_code=404, detail="Tenant data plane not found") from exc

    tunnels = [a for a in (plane.vpn_tunnel1_address, plane.vpn_tunnel2_address) if a]
    instructions = (
        f"Configure your on-prem VPN device (customer gateway {plane.customer_gateway_id}) "
        f"to establish {plane.routing_type} IPsec tunnels to the AWS tunnel outside IPs "
        f"{tunnels or '(pending terraform apply)'}. Advertise/allow only the agreed on-prem "
        f"CIDRs {plane.allowed_onprem_cidrs}. Download the device-specific configuration "
        f"from the AWS console for VPN connection {plane.vpn_connection_id}."
    )
    return OnboardingPackage(
        tenant_id=plane.tenant_id,
        tenant_name=plane.tenant_name,
        customer_gateway_id=plane.customer_gateway_id,
        customer_gateway_ip=None,
        aws_tunnel_outside_ips=tunnels,
        routing_type=plane.routing_type or "static",
        allowed_onprem_cidrs=list(plane.allowed_onprem_cidrs or []),
        instructions=instructions,
    )
