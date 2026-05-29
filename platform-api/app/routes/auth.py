"""Authentication routes.

`POST /api/auth/exchange` accepts a third-party JWT (Clerk or Supabase) and
returns a first-party platform-api access token bound to the caller's tenant
and user. Endpoints in this module are reachable without an existing
platform-api token, so they perform their own credential verification.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.clerk import verify_external_token
from app.auth.jwt import AuthError, create_access_token
from app.config import get_settings
from app.database import get_db
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.auth import AuthExchangeRequest, AuthTokenResponse, DirectLoginRequest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/exchange", response_model=AuthTokenResponse)
async def exchange_token(
    payload: AuthExchangeRequest,
    session: AsyncSession = Depends(get_db),
) -> AuthTokenResponse:
    settings = get_settings()
    try:
        external_claims = await verify_external_token(payload.token, provider=payload.provider)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    external_user_id = external_claims.get("sub")
    if not external_user_id:
        raise HTTPException(status_code=400, detail="External token missing `sub`")

    user = await session.scalar(select(User).where(User.external_id == external_user_id))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No platform-api user linked to external id {external_user_id}",
        )

    if payload.tenant_slug:
        tenant = await session.scalar(select(Tenant).where(Tenant.slug == payload.tenant_slug))
        if tenant is None or tenant.id != user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User does not belong to requested tenant",
            )

    access_token = create_access_token(
        sub=external_user_id,
        tenant_id=user.tenant_id,
        user_id=user.id,
        role=user.role,
    )
    tenant = await session.get(Tenant, user.tenant_id)
    return AuthTokenResponse(
        access_token=access_token,
        expires_in=settings.jwt_access_token_ttl_minutes * 60,
        tenant_id=user.tenant_id,
        user_id=user.id,
        role=user.role,
        is_super_admin=user.is_super_admin,
        tenant_slug=tenant.slug if tenant else None,
    )


@router.post("/login", response_model=AuthTokenResponse)
async def direct_login(
    payload: DirectLoginRequest,
    session: AsyncSession = Depends(get_db),
) -> AuthTokenResponse:
    """Authenticate with email and password (no external provider required)."""
    settings = get_settings()

    query = select(User).where(User.email == payload.email, User.is_active.is_(True))
    if payload.tenant_slug:
        tenant = await session.scalar(select(Tenant).where(Tenant.slug == payload.tenant_slug))
        if tenant is None:
            raise HTTPException(status_code=401, detail="Invalid email or password")
        query = query.where(User.tenant_id == tenant.id)

    user = await session.scalar(query)
    if user is None or not user.verify_password(payload.password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    access_token = create_access_token(
        sub=user.external_id or str(user.id),
        tenant_id=user.tenant_id,
        user_id=user.id,
        role=user.role,
    )
    login_tenant = await session.get(Tenant, user.tenant_id)
    return AuthTokenResponse(
        access_token=access_token,
        expires_in=settings.jwt_access_token_ttl_minutes * 60,
        tenant_id=user.tenant_id,
        user_id=user.id,
        role=user.role,
        is_super_admin=user.is_super_admin,
        tenant_slug=login_tenant.slug if login_tenant else None,
    )
