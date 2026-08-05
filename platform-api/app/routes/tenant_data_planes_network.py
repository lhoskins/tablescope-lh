"""Tenant data-plane networking artifacts.

Renders the host firewall script and the tenant's Docker Compose, attaches
VPN/VPC metadata (e.g. from Terraform outputs), reports health and produces the
customer VPN onboarding package.

All endpoints require super-admin.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.database import get_db
from app.routes.tenant_data_planes_crud import _read, _require_super_admin
from app.schemas.tenant_data_plane import (
    ComposePreview,
    FirewallScriptPreview,
    HealthCheckRequest,
    OnboardingPackage,
    ProvisionContainerResponse,
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
    TenantNotFound,
    TenantProvisioningService,
    VpnMetadata,
)

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

    generated = TenantComposeService().generate(layout, write=False)
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
    # Promote a pending tenant to active once its data plane is verified healthy
    # (container reachable, firewall applied, VDB dir present). VPN tunnels may
    # legitimately be down until the customer peer is configured.
    if (
        plane.status in ("provisioning", "container_pending")
        and report.teiid_status == "healthy"
        and report.firewall_status == "applied"
        and report.vdb_path_status == "ok"
    ):
        plane.status = "active"
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
