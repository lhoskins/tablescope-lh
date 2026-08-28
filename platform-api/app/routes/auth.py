"""Authentication routes.

`POST /api/auth/exchange` accepts a third-party JWT (Clerk or Supabase) and
returns a first-party platform-api access token bound to the caller's tenant
and user. Endpoints in this module are reachable without an existing
platform-api token, so they perform their own credential verification.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.clerk import verify_external_token
from app.auth.context import RequestContext
from app.auth.jwt import AuthError, create_access_token
from app.auth.membership import require_membership
from app.auth.rbac import Role, has_role
from app.config import get_settings
from app.database import get_db
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_auth_identity import UserAuthIdentity
from app.schemas.auth import (
    AuthExchangeRequest,
    AuthTokenResponse,
    CurrentUserResponse,
    DirectLoginRequest,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
)
from app.services.allowed_domains import enforce_allowed_domain
from app.services.email import send_transactional_email
from app.services.enterprise_auth import (
    record_identity_link,
    resolve_user_for_external_identity,
)
from app.services.mfa_phone_service import mfa_aal_for_user
from app.services.supabase_auth_service import SupabaseAuthService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


def _is_sso_claim(claims: dict[str, Any]) -> bool:
    """Detect whether a Supabase token represents an SSO/SAML session."""
    amr = claims.get("amr")
    if isinstance(amr, list):
        for entry in amr:
            if isinstance(entry, dict) and entry.get("method") == "sso":
                return True
            if entry == "sso":
                return True
    return False


def _provider_type_for_claims(provider: str, claims: dict[str, Any]) -> str:
    if provider == "supabase" and _is_sso_claim(claims):
        return "supabase_saml"
    if provider == "supabase":
        return "supabase_local"
    return provider


def _permissions_for_user(role: str, is_super_admin: bool = False) -> list[str]:
    """Derive fine-grained permissions from the user's role.

    This is a safe initial mapping until a dedicated permission-assignment UI
    exists. Tenant and root admins inherit the insight feedback reviewer right
    without needing an explicit ``insight_feedback.review`` permission claim.
    """
    permissions: list[str] = []
    if is_super_admin or has_role(role, Role.ADMIN):
        permissions.append("insight_feedback.review")
    return permissions


@router.get("/me", response_model=CurrentUserResponse)
async def get_current_user(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_membership),
) -> CurrentUserResponse:
    """Return the authenticated caller's identity and tenant for the app shell."""
    user = await session.get(User, context.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    tenant = await session.get(Tenant, context.tenant_id)
    return CurrentUserResponse(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        first_name=user.first_name,
        last_name=user.last_name,
        role=user.role,
        is_super_admin=user.is_super_admin,
        tenant_id=user.tenant_id,
        tenant_name=tenant.name if tenant else "",
        tenant_slug=tenant.slug if tenant else None,
        avatar_url=user.avatar_url,
        company_logo_url=tenant.logo_url if tenant else None,
        voice_input_enabled=tenant.voice_input_enabled if tenant else False,
        chat_attachments_enabled=tenant.chat_attachments_enabled if tenant else False,
        servicenow_itsm_dashboards_v2_enabled=(
            tenant.servicenow_itsm_dashboards_v2_enabled
            if tenant
            else get_settings().servicenow_itsm_dashboards_v2_enabled
        ),
        permissions=_permissions_for_user(user.role, user.is_super_admin),
    )


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

    provider_type = _provider_type_for_claims(payload.provider, external_claims)
    # SSO/SAML identities must be explicitly linked; do not fall back to email.
    allow_email_match = provider_type not in ("supabase_saml", "ldap_directory")
    fallback_to_user_external_id = provider_type != "supabase_saml"

    # Identity is unique per tenant, so when a tenant slug is supplied (every
    # /{slug}/login does) resolve the user within that tenant. This lets one
    # Supabase email belong to several tenants (e.g. root_admin in `root` and
    # tenant_admin in a customer tenant).
    tenant_id: int | None = None
    if payload.tenant_slug:
        tenant = await session.scalar(select(Tenant).where(Tenant.slug == payload.tenant_slug))
        if tenant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Tenant {payload.tenant_slug!r} not found",
            )
        tenant_id = tenant.id

    if tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant slug is required to exchange an external token",
        )

    email = external_claims.get("email")
    user = await resolve_user_for_external_identity(
        session,
        tenant_id=tenant_id,
        external_subject=external_user_id,
        provider_type=provider_type,
        email=email,
        fallback_to_user_external_id=fallback_to_user_external_id,
        allow_email_match=allow_email_match,
    )

    if user is None:
        if provider_type == "supabase_saml":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="SSO identity not linked to a TableScope user. Contact your administrator to map this identity.",
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not belong to requested tenant",
        )

    # Backfill a legacy identity record when the user was resolved by external_id
    # but no UserAuthIdentity row exists yet.
    identity = await session.scalar(
        select(UserAuthIdentity).where(
            UserAuthIdentity.tenant_id == user.tenant_id,
            UserAuthIdentity.provider_type == provider_type,
            UserAuthIdentity.external_subject == external_user_id,
        )
    )
    if identity is None:
        await record_identity_link(
            session,
            tenant_id=user.tenant_id,
            user_id=user.id,
            provider_type=provider_type,
            external_subject=external_user_id,
            verification_state="confirmed",
        )

    # A deactivated/blocked membership must not be able to obtain a token.
    if not user.is_active or (user.status or "active") != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your access to this tenant is inactive",
        )

    await enforce_allowed_domain(
        session,
        tenant_id=user.tenant_id,
        email=user.email,
        user_id=user.id,
        purpose="access",
    )

    # Derive the assurance level from the user's verified-phone record: aal2
    # while a recent SMS verification window is open, else aal1. This lets a
    # reload / re-login inside the window skip the SMS challenge.
    permissions = _permissions_for_user(user.role, user.is_super_admin)
    access_token = create_access_token(
        sub=external_user_id,
        tenant_id=user.tenant_id,
        user_id=user.id,
        role=user.role,
        permissions=permissions,
        extra_claims={"aal": await mfa_aal_for_user(session, user.id)},
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
        permissions=permissions,
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
    else:
        # TS-ISO-015: email is unique per-tenant, not globally -- without a
        # tenant_slug, a shared email across tenants previously resolved to
        # an arbitrary (DB-order-dependent) row via plain session.scalar(),
        # checking the password against whichever user happened to come
        # back first. Require the tenant explicitly whenever more than one
        # account shares this email instead of guessing.
        candidates = (await session.scalars(query)).all()
        if len(candidates) > 1:
            raise HTTPException(
                status_code=400,
                detail="Multiple accounts found for this email. Please specify your organization.",
            )
        user = candidates[0] if candidates else None

    if user is None or not user.verify_password(payload.password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    await enforce_allowed_domain(
        session,
        tenant_id=user.tenant_id,
        email=user.email,
        user_id=user.id,
        purpose="access",
    )

    permissions = _permissions_for_user(user.role, user.is_super_admin)
    access_token = create_access_token(
        sub=user.external_id or str(user.id),
        tenant_id=user.tenant_id,
        user_id=user.id,
        role=user.role,
        permissions=permissions,
        extra_claims={"aal": await mfa_aal_for_user(session, user.id)},
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
        permissions=permissions,
    )


@router.post("/refresh", response_model=AuthTokenResponse)
async def refresh_token(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_membership),
) -> AuthTokenResponse:
    """Return a new access token for an already-authenticated session.

    This lets the web client extend a session while the user is active,
    without waiting for the JWT to expire and trigger a full re-login.
    """
    settings = get_settings()
    user = await session.get(User, context.user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session no longer valid",
        )

    permissions = _permissions_for_user(user.role, user.is_super_admin)
    access_token = create_access_token(
        sub=context.claims.sub,
        tenant_id=user.tenant_id,
        user_id=user.id,
        role=user.role,
        permissions=permissions,
        extra_claims={"aal": context.claims.aal},
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
        permissions=permissions,
    )


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
async def forgot_password(
    payload: ForgotPasswordRequest,
    session: AsyncSession = Depends(get_db),
) -> ForgotPasswordResponse:
    """Send a password-reset email through Tablescope's transactional email.

    Supabase Auth does not have a custom SMTP provider configured in this
    project, so the reset link is generated via the GoTrue admin API and
    delivered through the application's own email channel. The link carries a
    one-time token_hash that the set-password page exchanges for a Supabase
    session with verifyOtp.
    """
    settings = get_settings()
    generic = ForgotPasswordResponse()
    tenant = await session.scalar(
        select(Tenant).where(Tenant.slug == payload.tenant_slug)
    )
    if tenant is None:
        return generic
    user = await session.scalar(
        select(User).where(
            User.email.ilike(payload.email),
            User.tenant_id == tenant.id,
            User.is_active.is_(True),
        )
    )
    if user is None or not user.external_id:
        return generic
    try:
        svc = SupabaseAuthService()
        action_link = await svc.generate_recovery_link(
            user.email,
            redirect_to=settings.app_base_url.rstrip("/"),
        )
        match = re.search(r"[?&]token=([0-9a-f]+)", action_link)
        token_hash = match.group(1) if match else None
        if not token_hash:
            logger.warning(
                "generate_recovery_link returned no token: %s", action_link
            )
            return generic
        reset_link = (
            f"{settings.app_base_url.rstrip('/')}/{payload.tenant_slug}/set-password"
            f"?token_hash={token_hash}&type=recovery"
        )
        await send_transactional_email(
            to=user.email,
            template="password_reset",
            variables={
                "first_name": user.first_name or "",
                "reset_link": reset_link,
                "expiration_time": "15 minutes",
            },
        )
    except Exception:
        logger.exception("Forgot-password flow failed for %s", payload.email)
    return generic
