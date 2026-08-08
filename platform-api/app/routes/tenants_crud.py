"""Tenant provisioning, deletion, listing, details, and document reprocessing.

Split from ``tenants.py``; siblings: ``tenants_settings.py``,
``tenants_security_policy.py`` and ``tenants_users.py``. The shared
authorization dependencies live here and are imported by those siblings.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.membership import require_membership
from app.auth.rbac import Role, require_role
from app.auth.tenant_roles import to_tenant_role
from app.database import get_db
from app.models.project import Project
from app.models.shared_vdb import SharedVDB
from app.models.tenant import Tenant
from app.models.tenant_data_plane import TenantDataPlane
from app.models.user import User
from app.models.user_vdb import UserVDB
from app.schemas.tenant import (
    TenantCreate,
    TenantDeleteResponse,
    TenantRead,
    TenantReprocessResponse,
)
from app.services.customer_folders import CustomerFolderError, CustomerFolderService
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
    """Get tenant details including users with VDB info and shared VDBs.

    Tenant admins may view their own tenant; root/super admins may view any tenant.
    """
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if (
        not context.is_service
        and context.tenant_id != tenant_id
        and context.role not in (Role.ROOT_ADMIN,)
        and not await _is_super_admin(session, context)
    ):
        raise HTTPException(status_code=403, detail="Cannot view another tenant")

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


async def _reprocess_tenant_documents(
    session: AsyncSession,
    context: RequestContext,
    tenant_id: int,
    force: bool = False,
) -> TenantReprocessResponse:
    """Enqueue a project-wide reprocess cascade for every project in a tenant."""
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

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

    return TenantReprocessResponse(
        tenant_id=tenant_id,
        status="queued",
        total_projects=len(project_ids),
        projects_queued=len(job_ids),
        projects_skipped=skipped,
        job_ids=job_ids,
        force=force,
    )


@router.post("/current/reprocess-documents", response_model=TenantReprocessResponse)
async def reprocess_current_tenant_documents(
    force: bool = False,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> TenantReprocessResponse:
    """Reprocess every document in every project for the calling tenant."""
    return await _reprocess_tenant_documents(session, context, context.tenant_id, force)


@router.post("/{tenant_id}/reprocess-documents", response_model=TenantReprocessResponse)
async def reprocess_tenant_documents(
    tenant_id: int,
    force: bool = False,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(_require_user_management),
) -> TenantReprocessResponse:
    """Reprocess every document in every project for a tenant.

    Tenant admins may reprocess their own tenant; root/super admins may
    reprocess any tenant.
    """
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
    return await _reprocess_tenant_documents(session, context, tenant_id, force)
