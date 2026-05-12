"""Tenant + user management routes.

Tenants are created by service callers (e.g. an internal admin tool calling
with `X-API-Key`) since a brand-new tenant has no users to authenticate.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext, get_request_context
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.tenant import TenantCreate, TenantRead, UserCreate, UserRead
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
    if not context.is_service:
        raise HTTPException(status_code=403, detail="Service-only endpoint")

    tenant = Tenant(slug=payload.slug, name=payload.name, external_id=payload.external_id)
    session.add(tenant)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Tenant slug or external_id already exists") from exc

    CustomerFolderService().ensure_tenant_folders(tenant.slug)
    return TenantRead.model_validate(tenant)


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
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="User already exists") from exc

    CustomerFolderService().ensure_user_folders(
        tenant.slug, payload.external_id or str(user.id)
    )
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
