"""Enterprise authentication settings and overview routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.ldap_connection import LdapConnection
from app.models.tenant import Tenant
from app.schemas.enterprise_auth import (
    EnterpriseAuthOverview,
    EnterpriseAuthSettingsRead,
    EnterpriseAuthSettingsUpdate,
)
from app.services.enterprise_auth import (
    audit_enterprise_auth_event,
    get_enterprise_auth_settings,
    update_enterprise_auth_settings,
)

router = APIRouter(prefix="/tenants", tags=["enterprise-auth"])


async def _get_or_create_ldap_connection(
    session: AsyncSession, tenant_id: int
) -> LdapConnection | None:
    settings = await get_enterprise_auth_settings(session, tenant_id)
    if settings.ldap_connection_id is None:
        return None
    return await session.get(LdapConnection, settings.ldap_connection_id)


async def _settings_read(
    session: AsyncSession, tenant_id: int
) -> EnterpriseAuthSettingsRead:
    settings = await get_enterprise_auth_settings(session, tenant_id)
    return EnterpriseAuthSettingsRead.model_validate(settings)


@router.get("/current/enterprise-auth", response_model=EnterpriseAuthOverview)
async def get_current_enterprise_auth_overview(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> EnterpriseAuthOverview:
    """Return a safe, read-only overview for the settings page."""
    tenant = await session.get(Tenant, context.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    settings = await get_enterprise_auth_settings(session, context.tenant_id)
    conn = await _get_or_create_ldap_connection(session, context.tenant_id)
    ldap_status = "off"
    if settings.ldap_enabled and conn is not None:
        ldap_status = conn.last_test_status or "configured"
    if not settings.ldap_enabled and conn is not None:
        ldap_status = "configured"
    sso_status = settings.sso_status or "off"
    if settings.sso_enabled:
        sso_status = settings.sso_status or "test"
    return EnterpriseAuthOverview(
        tenant_id=tenant.id,
        local_login_allowed=settings.local_login_allowed,
        enforce_2fa=tenant.enforce_2fa,
        ldap_status=ldap_status,
        sso_status=sso_status,
        sso_provider_display_name=settings.sso_provider_display_name,
        last_successful_directory_sync=conn.last_tested_at if conn else None,
        last_successful_sso_test=settings.sso_last_tested_at,
    )


@router.get("/current/enterprise-auth/settings", response_model=EnterpriseAuthSettingsRead)
async def get_current_enterprise_auth_settings(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> EnterpriseAuthSettingsRead:
    return await _settings_read(session, context.tenant_id)


@router.put("/current/enterprise-auth/settings", response_model=EnterpriseAuthSettingsRead)
async def update_current_enterprise_auth_settings(
    payload: EnterpriseAuthSettingsUpdate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> EnterpriseAuthSettingsRead:
    await get_enterprise_auth_settings(session, context.tenant_id)
    # Sensitive toggle changes require aal2 step-up, mirroring tenants_security_policy.py.
    if (
        (payload.ldap_enabled or payload.sso_enabled or payload.sso_required)
        and context.aal != "aal2"
    ):
        raise HTTPException(
            status_code=409,
            detail="Verify your own phone (step-up authentication) before enabling enterprise authentication.",
        )
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return await _settings_read(session, context.tenant_id)
    await update_enterprise_auth_settings(
        session, context.tenant_id, updates, updated_by=context.user_id
    )
    for key, value in updates.items():
        await audit_enterprise_auth_event(
            session,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            scope="enterprise_auth_settings",
            title=f"{key} changed to {value}",
        )
    await session.commit()
    return await _settings_read(session, context.tenant_id)
