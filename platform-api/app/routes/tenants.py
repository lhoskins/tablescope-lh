"""Tenant + user management routes.

Tenants can be created by service callers or by admin users.
Users within a tenant can be created by that tenant's admin.
"""

from __future__ import annotations

import logging

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.membership import require_membership
from app.auth.rbac import Role, require_role
from app.auth.tenant_roles import to_tenant_role, validate_tenant_role
from app.config import get_settings
from app.database import get_db
from app.models.project import Project
from app.models.shared_vdb import SharedVDB
from app.models.tenant import Tenant, TenantAllowedDomain
from app.models.tenant_data_plane import TenantDataPlane
from app.models.user import User
from app.models.user_vdb import UserVDB
from app.schemas.tenant import (
    AllowedDomainCreate,
    AllowedDomainRead,
    AllowedDomainsResponse,
    AllowedDomainsSettingsUpdate,
    CompanyLogoRead,
    TenantCreate,
    TenantDeleteResponse,
    TenantRead,
    UserCreate,
    UserRead,
    UserUpdate,
)
from app.services.allowed_domains import (
    enforce_allowed_domain,
    is_valid_domain,
    normalize_domain,
)
from app.services.company_logo_storage import (
    CompanyLogoValidationError,
    read_company_logo,
    store_company_logo,
    validate_company_logo,
)
from app.services.customer_folders import CustomerFolderError, CustomerFolderService
from app.services.email_service import EmailService
from app.services.supabase_auth_service import (
    SupabaseAdminError,
    SupabaseAuthService,
    SupabaseConfigError,
)
from app.services.tenant_deletion_service import (
    delete_tenant_folders,
    purge_app_tenant,
    undeploy_tenant_vdbs,
)
from app.services.tenant_teiid_resolver import TenantTeiidResolver
from app.services.vdb_management import VDBManagementService, VDBProvisioningError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tenants", tags=["tenants"])


async def _require_super_admin(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> RequestContext:
    """Only super-admins can provision new tenants."""
    if context.is_service:
        return context
    user = await session.get(User, context.user_id)
    if user is None or not user.is_super_admin:
        raise HTTPException(status_code=403, detail="Only super-admins can provision tenants")
    return context


async def _is_super_admin(session: AsyncSession, context: RequestContext) -> bool:
    user = await session.get(User, context.user_id)
    return bool(user and user.is_super_admin)


async def _require_user_management(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_membership),
) -> RequestContext:
    """User management is an admin duty within a tenant.

    Allowed for service callers, super-admins, the ``root_admin`` platform role
    (which administers the dedicated root tenant), and tenant-level admins.
    """
    if context.is_service:
        return context
    if await _is_super_admin(session, context):
        return context
    if context.role in (Role.ROOT_ADMIN, Role.TENANT_ADMIN, Role.ADMIN):
        return context
    raise HTTPException(
        status_code=403,
        detail="User management requires an admin role",
    )


async def _require_root_or_super(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_membership),
) -> RequestContext:
    """Platform-level tenant administration: list all tenants, delete any tenant,
    and view any tenant's details / VDB status.

    Allowed for service callers, super-admins, and the ``root_admin`` platform
    role (which lives in the dedicated root-admin tenant).
    """
    if context.is_service:
        return context
    if await _is_super_admin(session, context):
        return context
    if context.role == Role.ROOT_ADMIN:
        return context
    raise HTTPException(
        status_code=403,
        detail="Requires the platform root admin or a super admin",
    )


@router.post(
    "",
    response_model=TenantRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_tenant(
    payload: TenantCreate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(_require_super_admin),
) -> TenantRead:
    tenant = Tenant(slug=payload.slug, name=payload.name, external_id=payload.external_id)
    session.add(tenant)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Tenant slug or external_id already exists") from exc

    CustomerFolderService().ensure_tenant_folders(tenant.slug)

    # Create shared VDB for the tenant, targeting the dedicated container if bound.
    endpoint = await TenantTeiidResolver(session).resolve_for_org(tenant.id)
    vdb_svc = VDBManagementService(
        servlet_url=endpoint.servlet_url,
        pg_host=endpoint.pg_host,
        pg_port=endpoint.pg_port,
    )
    try:
        shared_result = await vdb_svc.create_shared_vdb(org_id=tenant.id)
        shared_vdb = SharedVDB(
            tenant_id=tenant.id,
            vdb_id=shared_result.vdb_id,
            vdb_username=shared_result.vdb_username,
            encrypted_password=shared_result.vdb_password,
            vdb_host=shared_result.vdb_host,
            vdb_port=shared_result.vdb_port,
            is_active=True,
            health_status="deployed",
        )
        session.add(shared_vdb)
        logger.info("Shared VDB created for tenant %s: %s", tenant.slug, shared_result.vdb_id)
    except VDBProvisioningError as exc:
        logger.warning("Failed to create shared VDB for tenant %s: %s", tenant.slug, exc)
    finally:
        await vdb_svc.aclose()

    # If a root user is specified, create them
    if payload.root_user_email:
        root_user = User(
            tenant_id=tenant.id,
            email=payload.root_user_email,
            display_name=payload.root_user_name or "Admin",
            role="admin",
        )
        if payload.root_user_password:
            root_user.set_password(payload.root_user_password)
        session.add(root_user)
        await session.flush()
        CustomerFolderService().ensure_user_folders(
            tenant.slug, root_user.external_id or str(root_user.id)
        )

        # Create and deploy user VDB for the root user in the tenant container.
        vdb_svc = VDBManagementService(
            servlet_url=endpoint.servlet_url,
            pg_host=endpoint.pg_host,
            pg_port=endpoint.pg_port,
        )
        try:
            user_result = await vdb_svc.create_user_vdb(
                org_id=tenant.id, user_id=root_user.id,
            )
            user_vdb = UserVDB(
                tenant_id=tenant.id,
                user_id=root_user.id,
                vdb_id=user_result.vdb_id,
                vdb_username=user_result.vdb_username,
                encrypted_password=user_result.vdb_password,
                vdb_host=user_result.vdb_host,
                vdb_port=user_result.vdb_port,
                is_active=True,
                health_status="deployed",
            )
            session.add(user_vdb)
            logger.info("User VDB created for root user %s: %s", root_user.email, user_result.vdb_id)
        except VDBProvisioningError as exc:
            logger.warning("Failed to create user VDB for root user %s: %s", root_user.email, exc)
        finally:
            await vdb_svc.aclose()

    await session.commit()
    await session.refresh(tenant)
    return TenantRead.model_validate(tenant)


@router.delete("/{tenant_id}", response_model=TenantDeleteResponse)
async def delete_tenant(
    tenant_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(_require_root_or_super),
) -> TenantDeleteResponse:
    """Delete an application (org) tenant and all of its data.

    Cascades: undeploys the tenant's shared + user VDBs from its Teiid, deletes
    all users, projects, saved queries, data sources and VDB records, and
    removes the tenant's customer folder tree.

    A tenant bound to an isolated data plane must be deleted from
    ``/admin/data-planes`` instead, so the dedicated container/network are also
    torn down (a host/root operation). Such a request is rejected here.
    """
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    super_admin = await session.scalar(
        select(User.id).where(
            User.tenant_id == tenant_id, User.is_super_admin.is_(True)
        )
    )
    if super_admin is not None:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete a tenant that contains a super-admin user.",
        )

    bound_plane = await session.scalar(
        select(TenantDataPlane).where(TenantDataPlane.org_tenant_id == tenant_id)
    )
    if bound_plane is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Tenant is bound to data plane '{bound_plane.tenant_id}'. "
                "Delete it from Data Planes (VPN) to also tear down the "
                "isolated container and network."
            ),
        )

    slug = tenant.slug

    # Undeploy VDBs from the tenant's resolved Teiid before purging the rows
    # (best-effort; a missing VDB does not block deletion).
    endpoint = await TenantTeiidResolver(session).resolve_for_org(tenant_id)
    vdb_svc = VDBManagementService(
        servlet_url=endpoint.servlet_url,
        pg_host=endpoint.pg_host,
        pg_port=endpoint.pg_port,
    )
    try:
        vdbs_undeployed = await undeploy_tenant_vdbs(session, tenant_id, vdb_svc)
    finally:
        await vdb_svc.aclose()

    deleted_rows = await purge_app_tenant(session, tenant_id)

    folders_removed = False
    try:
        folders_removed = delete_tenant_folders(slug)
    except (CustomerFolderError, OSError) as exc:
        logger.warning("Failed to remove folders for tenant %s: %s", slug, exc)

    await session.commit()

    return TenantDeleteResponse(
        tenant_id=tenant_id,
        slug=slug,
        deleted_rows=deleted_rows,
        vdbs_undeployed=vdbs_undeployed,
        folders_removed=folders_removed,
    )


@router.get("", response_model=list[TenantRead])
async def list_tenants(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> list[TenantRead]:
    """List tenants visible to the caller.

    Super-admins see all tenants. Regular admins see only their own.
    """
    if context.is_service or context.role == Role.ROOT_ADMIN:
        rows = await session.scalars(select(Tenant).order_by(Tenant.id))
        return [TenantRead.model_validate(t) for t in rows]

    user = await session.get(User, context.user_id)
    if user and user.is_super_admin:
        rows = await session.scalars(select(Tenant).order_by(Tenant.id))
        return [TenantRead.model_validate(t) for t in rows]

    tenant = await session.get(Tenant, context.tenant_id)
    return [TenantRead.model_validate(tenant)] if tenant else []


@router.get("/{tenant_id}/details")
async def get_tenant_details(
    tenant_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(_require_root_or_super),
) -> dict:
    """Get tenant details including users with VDB info and shared VDBs."""
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Get all users for this tenant
    users_result = await session.scalars(
        select(User).where(User.tenant_id == tenant_id).order_by(User.id)
    )
    users = list(users_result)

    # Get all user VDBs for this tenant
    user_vdbs_result = await session.scalars(
        select(UserVDB).where(UserVDB.tenant_id == tenant_id)
    )
    user_vdbs_by_user: dict[int, UserVDB] = {}
    for vdb in user_vdbs_result:
        user_vdbs_by_user[vdb.user_id] = vdb

    # Get shared VDBs for this tenant
    shared_vdbs_result = await session.scalars(
        select(SharedVDB).where(SharedVDB.tenant_id == tenant_id)
    )
    shared_vdbs = list(shared_vdbs_result)

    # Build user list with VDB info
    user_list = []
    for u in users:
        user_vdb = user_vdbs_by_user.get(u.id)
        vdb_info = None
        if user_vdb:
            vdb = user_vdb
            vdb_location = f"/opt/wildfly/teiidfiles/customers/{tenant_id}/{u.id}/vdb/{vdb.vdb_id}-vdb.xml"
            vdb_info = {
                "vdb_id": vdb.vdb_id,
                "vdb_name": f"{vdb.vdb_id}-vdb.xml",
                "health_status": vdb.health_status,
                "location": vdb_location,
                "is_active": vdb.is_active,
                "last_health_check": vdb.last_health_check.isoformat() if vdb.last_health_check else None,
            }
        user_list.append({
            "id": u.id,
            "email": u.email,
            "display_name": u.display_name,
            "role": to_tenant_role(u.role),
            "is_active": u.is_active,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "vdb": vdb_info,
        })

    # Build shared VDB list
    shared_list = []
    for sv in shared_vdbs:
        sv_location = f"/opt/wildfly/teiidfiles/customers/{tenant_id}/shared/vdb/{sv.vdb_id}-vdb.xml"
        shared_list.append({
            "id": sv.id,
            "vdb_id": sv.vdb_id,
            "vdb_name": f"{sv.vdb_id}-vdb.xml",
            "health_status": sv.health_status,
            "location": sv_location,
            "is_active": sv.is_active,
            "last_health_check": sv.last_health_check.isoformat() if sv.last_health_check else None,
        })

    return {
        "tenant": TenantRead.model_validate(tenant).model_dump(mode="json"),
        "users": user_list,
        "shared_vdbs": shared_list,
    }


@router.get("/me", response_model=TenantRead)
async def get_my_tenant(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_membership),
) -> TenantRead:
    tenant = await session.get(Tenant, context.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return TenantRead.model_validate(tenant)


# ---------------------------------------------------------------------------
# Company logo (tenant branding)
# ---------------------------------------------------------------------------


@router.get("/current/logo", response_model=CompanyLogoRead)
async def get_company_logo(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_membership),
) -> CompanyLogoRead:
    """Return the calling tenant's company logo URL (or null when unset).

    Any authenticated member of the tenant may read it.
    """
    tenant = await session.get(Tenant, context.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return CompanyLogoRead(logo_url=tenant.logo_url)


@router.post("/current/logo", response_model=CompanyLogoRead)
async def upload_company_logo(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> CompanyLogoRead:
    """Upload/replace the calling tenant's company logo (admins only).

    The logo is always stored against the caller's own tenant, so an admin can
    never overwrite another tenant's branding.
    """
    tenant = await session.get(Tenant, context.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    content = await file.read()
    try:
        ext = validate_company_logo(
            content=content,
            content_type=file.content_type,
            filename=file.filename,
        )
    except CompanyLogoValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    file_id = store_company_logo(
        tenant_id=tenant.id,
        content=content,
        ext=ext,
    )
    tenant.logo_file_id = file_id
    # Cache-bust on every upload so the new logo shows immediately.
    tenant.logo_url = f"/api/tenants/{tenant.id}/logo?v={file_id.split('.')[0]}"
    await session.commit()
    await session.refresh(tenant)

    logger.info("Company logo uploaded for tenant %d", tenant.id)
    return CompanyLogoRead(logo_url=tenant.logo_url)


@router.get("/{tenant_id}/logo")
async def get_company_logo_image(
    tenant_id: int,
    session: AsyncSession = Depends(get_db),
) -> Response:
    """Serve a tenant's company logo image by opaque URL (no path exposed)."""
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None or not tenant.logo_file_id:
        raise HTTPException(status_code=404, detail="No logo")

    result = read_company_logo(
        tenant_id=tenant.id,
        file_id=tenant.logo_file_id,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="No logo")
    content, content_type = result
    return Response(
        content=content,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )


def _user_read_tenant(user: User) -> UserRead:
    """Serialize a user with its role mapped to the tenant vocabulary."""
    data = UserRead.model_validate(user)
    return data.model_copy(update={"role": to_tenant_role(data.role)})


# ---------------------------------------------------------------------------
# Allowed Domains (tenant administration)
# ---------------------------------------------------------------------------


async def _allowed_domains_response(
    session: AsyncSession, tenant: Tenant
) -> AllowedDomainsResponse:
    rows = await session.scalars(
        select(TenantAllowedDomain)
        .where(TenantAllowedDomain.tenant_id == tenant.id)
        .order_by(TenantAllowedDomain.domain)
    )
    return AllowedDomainsResponse(
        enabled=tenant.allowed_domains_enabled,
        domains=[AllowedDomainRead.model_validate(r) for r in rows],
    )


@router.get(
    "/current/allowed-domains", response_model=AllowedDomainsResponse
)
async def get_allowed_domains(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> AllowedDomainsResponse:
    """Return the calling tenant's Allowed-Domains setting and domain list."""
    tenant = await session.get(Tenant, context.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return await _allowed_domains_response(session, tenant)


@router.put(
    "/current/allowed-domains/settings", response_model=AllowedDomainsResponse
)
async def update_allowed_domains_settings(
    payload: AllowedDomainsSettingsUpdate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> AllowedDomainsResponse:
    """Toggle the calling tenant's Allowed-Domains restriction on/off."""
    tenant = await session.get(Tenant, context.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    tenant.allowed_domains_enabled = payload.enabled
    await session.commit()
    await session.refresh(tenant)
    return await _allowed_domains_response(session, tenant)


@router.post(
    "/current/allowed-domains",
    response_model=AllowedDomainRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_allowed_domain(
    payload: AllowedDomainCreate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> AllowedDomainRead:
    """Add an email domain to the calling tenant's allow-list."""
    tenant = await session.get(Tenant, context.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    domain = normalize_domain(payload.domain)
    if not is_valid_domain(domain):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid domain. Use a bare domain like 'boeing.com' (no wildcards).",
        )

    existing = await session.scalar(
        select(TenantAllowedDomain).where(
            TenantAllowedDomain.tenant_id == tenant.id,
            TenantAllowedDomain.domain == domain,
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Domain already on the allow-list.",
        )

    row = TenantAllowedDomain(
        tenant_id=tenant.id,
        domain=domain,
        is_active=True,
        created_by=context.user_id,
    )
    session.add(row)
    # Adding a domain expresses intent to restrict access, so turn enforcement on
    # automatically. Admins can still disable it explicitly to stage domains.
    tenant.allowed_domains_enabled = True
    await session.commit()
    await session.refresh(row)
    return AllowedDomainRead.model_validate(row)


@router.delete(
    "/current/allowed-domains/{domain_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_allowed_domain(
    domain_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> Response:
    """Remove an email domain from the calling tenant's allow-list."""
    row = await session.get(TenantAllowedDomain, domain_id)
    if row is None or row.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Domain not found")
    await session.delete(row)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{tenant_id}/users",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_user(
    tenant_id: int,
    payload: UserCreate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(_require_user_management),
) -> UserRead:
    if not context.is_service and context.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="Cannot create users in another tenant")

    payload.role = validate_tenant_role(payload.role)

    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    existing = await session.scalar(
        select(User).where(User.tenant_id == tenant_id, User.email == payload.email)
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="User already exists")

    # Enforce the tenant's Allowed-Domains policy on the invitee's email. The
    # invitee is a new user (never the owner/admin) so they must match the list.
    await enforce_allowed_domain(
        session, tenant_id=tenant_id, email=payload.email, purpose="invite"
    )

    # Supabase is the primary authenticator: create/link a Supabase identity and
    # send a "set your password" invite that lands on the set-password page. No
    # local password is ever stored. If Supabase is unavailable, the user is NOT
    # created (no local fallback).
    settings = get_settings()
    setup_url = f"{settings.app_base_url}/{tenant.slug}/set-password"
    supa = SupabaseAuthService()
    try:
        supa_user = await supa.create_or_invite_user(
            payload.email,
            first_name=payload.display_name,
            redirect_to=setup_url,
        )
    except (SupabaseConfigError, SupabaseAdminError) as exc:
        logger.warning("Supabase user creation failed for %s: %s", payload.email, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication provider unavailable; user was not created",
        ) from exc

    user = await supa.link_local_user(
        session,
        supabase_user_id=supa_user.id,
        email=payload.email,
        tenant_id=tenant_id,
        role=payload.role,
        first_name=payload.display_name,
    )
    user.role = payload.role
    if payload.display_name:
        user.display_name = payload.display_name
    invite_link = supa_user.action_link
    if invite_link is None:
        try:
            invite_link = await supa.generate_magic_link(
                payload.email, redirect_to=setup_url
            )
        except SupabaseAdminError as exc:
            logger.warning("Could not generate set-password link for %s: %s", payload.email, exc)

    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="User already exists") from exc

    # The first user provisioned for a tenant becomes its owner — always exempt
    # from the Allowed-Domains restriction so an admin can never lock themselves
    # out. (No-op once an owner is set.)
    if tenant.owner_user_id is None:
        tenant.owner_user_id = user.id

    CustomerFolderService().ensure_user_folders(
        tenant.slug, user.external_id or str(user.id)
    )

    # Create and deploy user VDB — target the dedicated container if bound.
    endpoint = await TenantTeiidResolver(session).resolve_for_org(tenant_id)
    vdb_svc = VDBManagementService(
        servlet_url=endpoint.servlet_url,
        pg_host=endpoint.pg_host,
        pg_port=endpoint.pg_port,
    )
    try:
        vdb_result = await vdb_svc.create_user_vdb(
            org_id=tenant_id, user_id=user.id,
        )
        user_vdb = UserVDB(
            tenant_id=tenant_id,
            user_id=user.id,
            vdb_id=vdb_result.vdb_id,
            vdb_username=vdb_result.vdb_username,
            encrypted_password=vdb_result.vdb_password,
            vdb_host=vdb_result.vdb_host,
            vdb_port=vdb_result.vdb_port,
            is_active=True,
            health_status="deployed",
        )
        session.add(user_vdb)
        logger.info("User VDB created for user %s: %s", user.email, vdb_result.vdb_id)
    except VDBProvisioningError as exc:
        logger.warning("Failed to create user VDB for user %s: %s", user.email, exc)
    finally:
        await vdb_svc.aclose()

    await session.commit()
    await session.refresh(user)

    # Send the branded magic-link invite (best-effort; never fails user creation).
    if invite_link is not None:
        try:
            await EmailService().send_transactional_email(
                to=payload.email,
                template="user_invitation",
                variables={
                    "first_name": payload.display_name or "",
                    "inviter_name": "A Tablescope administrator",
                    "workspace_name": tenant.name,
                    "role_name": payload.role.replace("_", " ").title(),
                    "invitation_link": invite_link,
                    "expiration_date": "in 24 hours",
                },
                tenant_id=tenant_id,
            )
        except Exception as exc:  # delivery is best-effort
            logger.warning("Failed to send invite email to %s: %s", payload.email, exc)

    return _user_read_tenant(user)


@router.get("/{tenant_id}/users", response_model=list[UserRead])
async def list_users(
    tenant_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(_require_user_management),
) -> list[UserRead]:
    if not context.is_service and context.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="Cannot list users in another tenant")
    rows = await session.scalars(select(User).where(User.tenant_id == tenant_id).order_by(User.id))
    return [_user_read_tenant(u) for u in rows]


@router.put(
    "/{tenant_id}/users/{user_id}",
    response_model=UserRead,
)
async def update_user(
    tenant_id: int,
    user_id: int,
    payload: UserUpdate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(_require_user_management),
) -> UserRead:
    if not context.is_service and context.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="Cannot update users in another tenant")
    user = await session.get(User, user_id)
    if user is None or user.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="User not found")
    if payload.display_name is not None:
        user.display_name = payload.display_name
    if payload.role is not None:
        user.role = validate_tenant_role(payload.role)
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.password is not None:
        user.set_password(payload.password)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return _user_read_tenant(user)


@router.delete(
    "/{tenant_id}/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def deactivate_user(
    tenant_id: int,
    user_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(_require_user_management),
) -> Response:
    if not context.is_service and context.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="Cannot deactivate users in another tenant")
    user = await session.get(User, user_id)
    if user is None or user.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = False
    session.add(user)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{tenant_id}/users/{user_id}/permanent",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_user_permanently(
    tenant_id: int,
    user_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(_require_user_management),
) -> Response:
    """Hard-delete an inactive user. Only works on deactivated users."""
    if not context.is_service and context.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="Cannot delete users in another tenant")
    user = await session.get(User, user_id)
    if user is None or user.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_active:
        raise HTTPException(status_code=400, detail="User must be deactivated before permanent deletion")
    await session.delete(user)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{tenant_id}/reprocess-documents")
async def reprocess_tenant_documents(
    tenant_id: int,
    force: bool = False,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(_require_user_management),
) -> dict:
    """Reprocess every document in every project for a tenant.

    Enqueues one project-wide reprocess cascade per project.  Each cascade
    profiles changed documents (or all documents when ``force=true``) and
    rebuilds the project's knowledge graph last.  Duplicate enqueues for a
    project coalesce onto its in-flight job.
    """
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if (
        not context.is_service
        and context.tenant_id != tenant_id
        and context.role != Role.ROOT_ADMIN
        and not await _is_super_admin(session, context)
    ):
        raise HTTPException(
            status_code=403,
            detail="Cannot reprocess documents for another tenant",
        )

    project_ids = (
        await session.scalars(select(Project.id).where(Project.tenant_id == tenant_id))
    ).all()

    from app.tasks.workflows import enqueue_reprocess_project

    job_ids: list[str] = []
    skipped = 0
    for project_id in project_ids:
        job_id = await enqueue_reprocess_project(
            tenant_id=tenant_id,
            project_id=project_id,
            user_id=context.user_id,
            force=force,
        )
        if job_id:
            job_ids.append(job_id)
        else:
            skipped += 1

    return {
        "tenant_id": tenant_id,
        "status": "queued",
        "total_projects": len(project_ids),
        "projects_queued": len(job_ids),
        "projects_skipped": skipped,
        "job_ids": job_ids,
        "force": force,
    }
