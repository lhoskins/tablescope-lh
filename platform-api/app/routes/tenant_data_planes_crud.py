"""Tenant data-plane registry CRUD.

Create/list/read/delete tenant data planes and bind them to application
tenants. Also hosts the shared super-admin guard and provisioning helpers used
by the sibling tenant-data-plane route modules.

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
    DeleteDataPlaneResponse,
    TenantDataPlaneCreate,
    TenantDataPlaneRead,
)
from app.services.customer_folders import CustomerFolderError, CustomerFolderService
from app.services.tenant_deletion_service import (
    delete_tenant_folders,
    purge_app_tenant,
    render_teardown_script,
)
from app.services.tenant_layout import InvalidTenantId
from app.services.tenant_provisioning_service import (
    InvalidVpnMode,
    TenantAlreadyExists,
    TenantNotFound,
    TenantProvisioningService,
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
        # the dedicated container. Flush so the resolver (which looks the plane
        # up by org_tenant_id) sees the binding when routing the VDB creation.
        plane.org_tenant_id = tenant.id
        await session.flush()
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

    # Flush so the resolver sees the new binding when routing VDB creation to
    # the dedicated container.
    plane.org_tenant_id = org_id
    await session.flush()
    await _provision_vdbs_for_tenant(session, org_tenant_id=org_id, user_id=root_user_id)

    await session.commit()
    await session.refresh(plane)
    return _read(plane)


@router.delete("/{tenant_id}", response_model=DeleteDataPlaneResponse)
async def delete_data_plane(
    tenant_id: str,
    delete_app_tenant: bool = True,
    session: AsyncSession = Depends(get_db),
    _: RequestContext = Depends(_require_super_admin),
) -> DeleteDataPlaneResponse:
    """Decommission a tenant data plane.

    Cascades: deletes the bound application tenant's users, projects, data
    sources and VDB records, removes the tenant's customer folders, deletes the
    secret references and the data-plane registry row, and returns a host
    teardown script that removes the isolated Docker container, network and
    on-host VDB directory (root/Docker ops the least-privilege API cannot run).
    """
    svc = TenantProvisioningService(session)
    try:
        plane = await svc.get(tenant_id)
    except TenantNotFound as exc:
        raise HTTPException(status_code=404, detail="Tenant data plane not found") from exc

    layout = svc.layout_for(plane)
    org_tenant_id = plane.org_tenant_id
    deleted_rows: dict[str, int] = {}
    folders_removed = False
    app_tenant_deleted = False

    if org_tenant_id is not None and delete_app_tenant:
        org_tenant = await session.get(Tenant, org_tenant_id)
        if org_tenant is not None:
            slug = org_tenant.slug
            deleted_rows = await purge_app_tenant(session, org_tenant_id)
            app_tenant_deleted = deleted_rows.get("tenants", 0) > 0
            try:
                folders_removed = delete_tenant_folders(slug)
            except (CustomerFolderError, OSError) as exc:
                logger.warning("Failed to remove folders for tenant %s: %s", slug, exc)

    # Drop the secret references then the data-plane row (explicit, so it works
    # the same on SQLite tests as on Postgres FK cascade).
    from sqlalchemy import delete as sa_delete

    from app.models.tenant_data_plane import TenantSecretRef

    await session.execute(
        sa_delete(TenantSecretRef).where(TenantSecretRef.data_plane_id == plane.id)
    )
    await session.delete(plane)
    await session.commit()

    teardown_script = render_teardown_script(layout)
    note = (
        f"Data plane '{tenant_id}' removed from the registry. "
        "Run the teardown script on the EC2 host to remove the isolated "
        f"container ({layout.teiid_container_name}), the tenant network "
        f"({layout.docker_network_name}) and the on-host VDB directory "
        f"({layout.tenant_root})."
    )
    return DeleteDataPlaneResponse(
        tenant_id=tenant_id,
        org_tenant_id=org_tenant_id,
        app_tenant_deleted=app_tenant_deleted,
        deleted_rows=deleted_rows,
        folders_removed=folders_removed,
        teardown_script=teardown_script,
        teardown_script_path=None,
        note=note,
    )
