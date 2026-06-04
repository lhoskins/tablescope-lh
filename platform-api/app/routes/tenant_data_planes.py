"""Tenant data-plane onboarding & visibility API.

Manages the multi-tenant on-prem data-access registry: create a tenant data
plane, attach VPN/VPC metadata (e.g. from Terraform outputs), render the
tenant's Docker Compose and host firewall artifacts, report health, and produce
a customer VPN onboarding package.

All endpoints require super-admin. Mounted at ``/api/tenant-data-planes`` (the
plan's ``/api/tenants`` name is already taken by org/tenant management).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.shared_vdb import SharedVDB
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_vdb import UserVDB
from app.schemas.tenant_data_plane import (
    BindAppTenantIn,
    ComposePreview,
    FirewallScriptPreview,
    HealthCheckRequest,
    OnboardingPackage,
    ProvisionContainerResponse,
    TenantDataPlaneCreate,
    TenantDataPlaneRead,
    VpnMetadataIn,
)
from app.services.customer_folders import CustomerFolderService
from app.services.tenant_firewall_service import (
    FIREWALL_CONFIG_DIR,
    SYSTEMD_UNIT_PATH,
    TenantFirewallService,
)
from app.services.tenant_health_service import TenantHealthService
from app.services.tenant_layout import InvalidTenantId
from app.services.tenant_provisioning_service import (
    InvalidVpnMode,
    TenantAlreadyExists,
    TenantNotFound,
    TenantProvisioningService,
    VpnMetadata,
)
from app.services.tenant_teiid_resolver import TenantTeiidResolver
from app.services.vdb_management import VDBManagementService, VDBProvisioningError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tenant-data-planes", tags=["tenant-data-planes"])


async def _require_super_admin(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> RequestContext:
    if context.is_service:
        return context
    user = await session.get(User, context.user_id)
    if user is None or not user.is_super_admin:
        raise HTTPException(status_code=403, detail="Only super-admins can manage tenant data planes")
    return context


def _read(plane) -> TenantDataPlaneRead:
    return TenantDataPlaneRead(**plane.to_dict(include_network=True))


async def _provision_vdbs_for_tenant(
    session: AsyncSession,
    *,
    org_tenant_id: int,
    user_id: int | None,
) -> None:
    """Create the shared (and optional user) VDBs inside the tenant's container.

    Routing comes from ``TenantTeiidResolver.resolve_for_org`` so the VDBs land
    in the dedicated container when the org tenant is bound to a data plane.
    Failures are non-fatal (logged) so a not-yet-running container doesn't block
    the tenant record.
    """
    endpoint = await TenantTeiidResolver(session).resolve_for_org(org_tenant_id)
    vdb_svc = VDBManagementService(
        servlet_url=endpoint.servlet_url,
        pg_host=endpoint.pg_host,
        pg_port=endpoint.pg_port,
    )
    try:
        shared_result = await vdb_svc.create_shared_vdb(org_id=org_tenant_id)
        session.add(SharedVDB(
            tenant_id=org_tenant_id,
            vdb_id=shared_result.vdb_id,
            vdb_username=shared_result.vdb_username,
            encrypted_password=shared_result.vdb_password,
            vdb_host=shared_result.vdb_host,
            vdb_port=shared_result.vdb_port,
            is_active=True,
            health_status="deployed",
        ))
        logger.info("Shared VDB created for org tenant %s: %s", org_tenant_id, shared_result.vdb_id)
    except VDBProvisioningError as exc:
        logger.warning("Shared VDB not created for org %s (container may not be up): %s", org_tenant_id, exc)
    finally:
        await vdb_svc.aclose()

    if user_id is None:
        return

    vdb_svc = VDBManagementService(
        servlet_url=endpoint.servlet_url,
        pg_host=endpoint.pg_host,
        pg_port=endpoint.pg_port,
    )
    try:
        user_result = await vdb_svc.create_user_vdb(org_id=org_tenant_id, user_id=user_id)
        session.add(UserVDB(
            tenant_id=org_tenant_id,
            user_id=user_id,
            vdb_id=user_result.vdb_id,
            vdb_username=user_result.vdb_username,
            encrypted_password=user_result.vdb_password,
            vdb_host=user_result.vdb_host,
            vdb_port=user_result.vdb_port,
            is_active=True,
            health_status="deployed",
        ))
        logger.info("User VDB created for user %s: %s", user_id, user_result.vdb_id)
    except VDBProvisioningError as exc:
        logger.warning("User VDB not created for user %s (container may not be up): %s", user_id, exc)
    finally:
        await vdb_svc.aclose()


async def _create_app_tenant(
    session: AsyncSession,
    *,
    slug: str,
    name: str,
    admin_email: str,
    admin_password: str,
) -> tuple[Tenant, User]:
    """Create an application tenant + root admin user and their folders."""
    tenant = Tenant(slug=slug, name=name)
    session.add(tenant)
    await session.flush()
    CustomerFolderService().ensure_tenant_folders(tenant.slug)

    root_user = User(
        tenant_id=tenant.id,
        email=admin_email,
        display_name="Admin",
        role="admin",
    )
    root_user.set_password(admin_password)
    session.add(root_user)
    await session.flush()
    CustomerFolderService().ensure_user_folders(
        tenant.slug, root_user.external_id or str(root_user.id)
    )
    return tenant, root_user


@router.post("", response_model=TenantDataPlaneRead, status_code=status.HTTP_201_CREATED)
async def create_data_plane(
    payload: TenantDataPlaneCreate,
    session: AsyncSession = Depends(get_db),
    _: RequestContext = Depends(_require_super_admin),
) -> TenantDataPlaneRead:
    # If the caller wants a fully usable tenant in one shot, validate the
    # required app-tenant fields before we create any infra.
    if payload.create_app_tenant:
        if not payload.app_tenant_admin_email or not payload.app_tenant_admin_password:
            raise HTTPException(
                status_code=422,
                detail="app_tenant_admin_email and app_tenant_admin_password are required "
                "when create_app_tenant is true.",
            )
        # Ensure the slug isn't already taken as an org tenant.
        existing_tenant = await session.scalar(
            select(Tenant).where(Tenant.slug == payload.tenant_id)
        )
        if existing_tenant is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Application tenant with slug '{payload.tenant_id}' already exists.",
            )

    svc = TenantProvisioningService(session)
    try:
        plane, _layout = await svc.create(
            tenant_id=payload.tenant_id,
            tenant_name=payload.tenant_name,
            allowed_onprem_cidrs=payload.allowed_onprem_cidrs,
            org_tenant_id=payload.org_tenant_id,
            routing_type=payload.routing_type,
            vpn_mode=payload.vpn_mode,
            shared_ec2_instance_id=payload.shared_ec2_instance_id,
            shared_services_vpc_id=payload.shared_services_vpc_id,
            teiid_api_key_secret_ref=payload.teiid_api_key_secret_ref,
        )
    except (InvalidTenantId, InvalidVpnMode) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TenantAlreadyExists as exc:
        raise HTTPException(status_code=409, detail=f"Tenant '{exc}' already exists") from exc

    # --- Unified provisioning: create the app tenant + root admin + VDBs ---
    if payload.create_app_tenant:
        assert payload.app_tenant_admin_email is not None  # validated above
        assert payload.app_tenant_admin_password is not None  # validated above
        tenant, root_user = await _create_app_tenant(
            session,
            slug=payload.tenant_id,
            name=payload.tenant_name,
            admin_email=payload.app_tenant_admin_email,
            admin_password=payload.app_tenant_admin_password,
        )
        # Bind the data plane to this app tenant, then provision its VDBs in
        # the dedicated container.
        plane.org_tenant_id = tenant.id
        await _provision_vdbs_for_tenant(
            session, org_tenant_id=tenant.id, user_id=root_user.id
        )

    await session.commit()
    await session.refresh(plane)
    return _read(plane)


@router.get("", response_model=list[TenantDataPlaneRead])
async def list_data_planes(
    session: AsyncSession = Depends(get_db),
    _: RequestContext = Depends(_require_super_admin),
) -> list[TenantDataPlaneRead]:
    svc = TenantProvisioningService(session)
    return [_read(p) for p in await svc.list_planes()]


@router.get("/app-tenants")
async def list_app_tenants(
    session: AsyncSession = Depends(get_db),
    _: RequestContext = Depends(_require_super_admin),
) -> list[dict]:
    """Return existing app/org tenants for the 'Link existing' dropdown."""
    tenants = (await session.scalars(select(Tenant).order_by(Tenant.id))).all()
    return [{"id": t.id, "slug": t.slug, "name": t.name} for t in tenants]


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


@router.get("/{tenant_id}", response_model=TenantDataPlaneRead)
async def get_data_plane(
    tenant_id: str,
    session: AsyncSession = Depends(get_db),
    _: RequestContext = Depends(_require_super_admin),
) -> TenantDataPlaneRead:
    svc = TenantProvisioningService(session)
    try:
        plane = await svc.get(tenant_id)
    except TenantNotFound as exc:
        raise HTTPException(status_code=404, detail="Tenant data plane not found") from exc
    return _read(plane)


@router.post("/{tenant_id}/bind-app-tenant", response_model=TenantDataPlaneRead)
async def bind_app_tenant(
    tenant_id: str,
    payload: BindAppTenantIn,
    session: AsyncSession = Depends(get_db),
    _: RequestContext = Depends(_require_super_admin),
) -> TenantDataPlaneRead:
    """Bind an *existing* data plane to an application tenant.

    Use this for data planes that were provisioned before an app tenant existed
    (e.g. the live ``acme`` plane). Either link an existing org tenant by id, or
    create a new app tenant (slug + root admin). Once bound, that tenant's
    serving path routes to this data plane's dedicated Teiid container.
    """
    svc = TenantProvisioningService(session)
    try:
        plane = await svc.get(tenant_id)
    except TenantNotFound as exc:
        raise HTTPException(status_code=404, detail="Tenant data plane not found") from exc

    if payload.org_tenant_id is None and not payload.new_tenant_slug:
        raise HTTPException(
            status_code=422,
            detail="Provide either org_tenant_id (link existing) or new_tenant_slug (create new).",
        )

    root_user_id: int | None = None
    if payload.new_tenant_slug:
        if not payload.admin_email or not payload.admin_password:
            raise HTTPException(
                status_code=422,
                detail="admin_email and admin_password are required when creating a new app tenant.",
            )
        existing = await session.scalar(
            select(Tenant).where(Tenant.slug == payload.new_tenant_slug)
        )
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Application tenant with slug '{payload.new_tenant_slug}' already exists.",
            )
        tenant, root_user = await _create_app_tenant(
            session,
            slug=payload.new_tenant_slug,
            name=payload.new_tenant_name or payload.new_tenant_slug,
            admin_email=payload.admin_email,
            admin_password=payload.admin_password,
        )
        org_id = tenant.id
        root_user_id = root_user.id
    else:
        assert payload.org_tenant_id is not None
        existing_tenant = await session.get(Tenant, payload.org_tenant_id)
        if existing_tenant is None:
            raise HTTPException(
                status_code=404, detail=f"Application tenant id {payload.org_tenant_id} not found."
            )
        org_id = existing_tenant.id

    plane.org_tenant_id = org_id
    await _provision_vdbs_for_tenant(session, org_tenant_id=org_id, user_id=root_user_id)

    await session.commit()
    await session.refresh(plane)
    return _read(plane)


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
