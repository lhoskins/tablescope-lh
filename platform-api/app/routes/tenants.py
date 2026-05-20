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
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.tenant import (
    TenantCreate,
    TenantRead,
    UserCreate,
    UserRead,
    UserUpdate,
)
from app.services.customer_folders import CustomerFolderService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.post(
    "",
    response_model=TenantRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_tenant(
    payload: TenantCreate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> TenantRead:
    tenant = Tenant(slug=payload.slug, name=payload.name, external_id=payload.external_id)
    session.add(tenant)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Tenant slug or external_id already exists") from exc

    CustomerFolderService().ensure_tenant_folders(tenant.slug)

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

    await session.commit()
    await session.refresh(tenant)
    return TenantRead.model_validate(tenant)


@router.get("", response_model=list[TenantRead])
async def list_tenants(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> list[TenantRead]:
    """List all tenants. Service accounts see all; admin users see only their own."""
    if context.is_service:
        rows = await session.scalars(select(Tenant).order_by(Tenant.id))
    else:
        rows = await session.scalars(
            select(Tenant).where(Tenant.id == context.tenant_id)
        )
    return [TenantRead.model_validate(t) for t in rows]


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


@router.put("/{tenant_id}/users/{user_id}", response_model=UserRead)
async def update_user(
    tenant_id: int,
    user_id: int,
    payload: UserUpdate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> UserRead:
    """Update a user's role, display name, active status, or password."""
    if not context.is_service and context.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="Cannot modify users in another tenant")

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

    await session.commit()
    await session.refresh(user)
    return UserRead.model_validate(user)


@router.delete("/{tenant_id}/users/{user_id}")
async def deactivate_user(
    tenant_id: int,
    user_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> Response:
    """Deactivate a user (soft delete)."""
    if not context.is_service and context.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="Cannot modify users in another tenant")

    user = await session.get(User, user_id)
    if user is None or user.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="User not found")

    if user.id == context.user_id:
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")

    user.is_active = False
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
