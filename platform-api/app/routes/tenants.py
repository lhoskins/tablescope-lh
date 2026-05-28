"""Tenant + user management routes.

Tenants can be created by service callers or by admin users.
Users within a tenant can be created by that tenant's admin.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext, get_request_context
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.shared_vdb import SharedVDB
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_vdb import UserVDB
from app.schemas.tenant import (
    TenantCreate,
    TenantRead,
    UserCreate,
    UserRead,
    UserUpdate,
)
from app.services.customer_folders import CustomerFolderService
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

    # Create shared VDB for the tenant
    vdb_svc = VDBManagementService()
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

        # Create and deploy user VDB for the root user
        vdb_svc = VDBManagementService()
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


@router.get("", response_model=list[TenantRead])
async def list_tenants(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> list[TenantRead]:
    """List tenants visible to the caller.

    Super-admins see all tenants. Regular admins see only their own.
    """
    if context.is_service:
        rows = await session.scalars(select(Tenant).order_by(Tenant.id))
        return [TenantRead.model_validate(t) for t in rows]

    user = await session.get(User, context.user_id)
    if user and user.is_super_admin:
        rows = await session.scalars(select(Tenant).order_by(Tenant.id))
        return [TenantRead.model_validate(t) for t in rows]

    tenant = await session.get(Tenant, context.tenant_id)
    return [TenantRead.model_validate(tenant)] if tenant else []


@router.get("/me", response_model=TenantRead)
async def get_my_tenant(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
) -> TenantRead:
    tenant = await session.get(Tenant, context.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return TenantRead.model_validate(tenant)


@router.post(
    "/{tenant_id}/users",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_user(
    tenant_id: int,
    payload: UserCreate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> UserRead:
    if not context.is_service and context.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="Cannot create users in another tenant")

    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    user = User(
        tenant_id=tenant_id,
        email=payload.email,
        display_name=payload.display_name,
        role=payload.role,
        external_id=payload.external_id,
    )
    if payload.password:
        user.set_password(payload.password)
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="User already exists") from exc

    CustomerFolderService().ensure_user_folders(
        tenant.slug, payload.external_id or str(user.id)
    )

    # Create and deploy user VDB
    vdb_svc = VDBManagementService()
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
    return UserRead.model_validate(user)


@router.get("/{tenant_id}/users", response_model=list[UserRead])
async def list_users(
    tenant_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
) -> list[UserRead]:
    if not context.is_service and context.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="Cannot list users in another tenant")
    rows = await session.scalars(select(User).where(User.tenant_id == tenant_id).order_by(User.id))
    return [UserRead.model_validate(u) for u in rows]


@router.put(
    "/{tenant_id}/users/{user_id}",
    response_model=UserRead,
)
async def update_user(
    tenant_id: int,
    user_id: int,
    payload: UserUpdate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> UserRead:
    if not context.is_service and context.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="Cannot update users in another tenant")
    user = await session.get(User, user_id)
    if user is None or user.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="User not found")
    if payload.display_name is not None:
        user.display_name = payload.display_name
    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.password is not None:
        user.set_password(payload.password)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return UserRead.model_validate(user)


@router.delete(
    "/{tenant_id}/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def deactivate_user(
    tenant_id: int,
    user_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
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
    context: RequestContext = Depends(require_role(Role.ADMIN)),
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
