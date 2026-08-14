"""Public enterprise authentication routes: tenant policy, SSO start, and callback."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.tenant import Tenant
from app.schemas.enterprise_auth import (
    SsoCallbackQuery,
    SsoStartRequest,
    SsoStartResponse,
    TenantAuthPolicyResponse,
)
from app.services.enterprise_auth import decrypt_sso_provider_id, get_enterprise_auth_settings
from app.services.sso_provider_service import SsoProviderService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/tenant-policy/{slug}", response_model=TenantAuthPolicyResponse)
async def get_tenant_auth_policy(
    slug: str,
    session: AsyncSession = Depends(get_db),
) -> TenantAuthPolicyResponse:
    tenant = await session.scalar(select(Tenant).where(Tenant.slug == slug))
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    settings = await get_enterprise_auth_settings(session, tenant.id)
    return TenantAuthPolicyResponse(
        tenant_slug=tenant.slug,
        tenant_display_name=tenant.name,
        local_login_allowed=settings.local_login_allowed,
        sso_enabled=settings.sso_enabled,
        sso_required=settings.sso_required,
        sso_button_label=settings.sso_provider_display_name or "Sign in with SSO",
    )


@router.post("/sso/start", response_model=SsoStartResponse)
async def start_sso(
    payload: SsoStartRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> SsoStartResponse:
    tenant = await session.scalar(select(Tenant).where(Tenant.slug == payload.tenant_slug))
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    settings = await get_enterprise_auth_settings(session, tenant.id)
    if not settings.sso_enabled:
        raise HTTPException(status_code=403, detail="SSO is not enabled for this tenant")
    provider_id = decrypt_sso_provider_id(settings.sso_provider_id_encrypted)
    if not provider_id:
        raise HTTPException(status_code=503, detail="SSO provider not configured")

    base_url = str(request.base_url).rstrip("/")
    callback_url = f"{base_url}/{payload.tenant_slug}/sso/callback"
    if payload.return_path and payload.return_path.startswith("/"):
        next_path = payload.return_path.lstrip("/")
        callback_url += f"?next={next_path}"

    service = SsoProviderService()
    try:
        url = await service.start_sso_url(provider_id=provider_id, redirect_to=callback_url)
    except Exception as exc:
        logger.exception("SSO start failed for tenant %s", payload.tenant_slug)
        raise HTTPException(status_code=503, detail=f"Could not start SSO: {exc}") from exc
    return SsoStartResponse(redirect_url=url)


@router.get("/sso/callback")
async def sso_callback(
    query: SsoCallbackQuery = Depends(),
) -> dict[str, str]:
    """Server-side SAML/OAuth callback.

    The real Supabase SAML flow returns tokens in the browser URL fragment after
    the ACS redirect, so the browser should hit the Next.js `/{slug}/sso/callback`
    page and exchange the access token with `/api/auth/exchange`. This endpoint
    is kept for any server-to-server flows that pass a `code` parameter.
    """
    if query.error:
        logger.warning("SSO callback error: %s - %s", query.error, query.error_description)
        raise HTTPException(status_code=401, detail=query.error)
    if query.code:
        # In a PKCE/OAuth2 code flow, the server can exchange the code for a
        # Supabase session here. The current implementation expects the browser
        # to handle the exchange via the frontend callback page.
        return {"status": "code_received", "code": query.code}
    return {"status": "ok", "detail": "Tokens must be exchanged in the browser callback page"}
