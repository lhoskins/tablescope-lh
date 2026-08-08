"""Tenant security policy: allowed email domains and 2FA enforcement.

Split from ``tenants.py``; siblings: ``tenants_crud.py``,
``tenants_settings.py`` and ``tenants_users.py``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.config import get_settings
from app.database import get_db
from app.models.audit_event import AuditEvent
from app.models.tenant import Tenant, TenantAllowedDomain
from app.schemas.tenant import (
    AllowedDomainCreate,
    AllowedDomainRead,
    AllowedDomainsResponse,
    AllowedDomainsSettingsUpdate,
    Enforce2faSettingsResponse,
    Enforce2faSettingsUpdate,
)
from app.services.allowed_domains import is_valid_domain, normalize_domain

router = APIRouter(prefix="/tenants", tags=["tenants"])

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


async def _set_enforce_2fa(
    session: AsyncSession,
    context: RequestContext,
    tenant_id: int,
    payload: Enforce2faSettingsUpdate,
) -> Enforce2faSettingsResponse:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if payload.enabled and not get_settings().twilio_verify_configured:
        raise HTTPException(
            status_code=503,
            detail="Two-factor authentication cannot be enabled: the SMS "
                   "provider is not configured for this deployment.",
        )
    if payload.enabled and context.aal != "aal2":
        raise HTTPException(
            status_code=409,
            detail="Verify your own phone (step-up authentication) before "
                   "requiring 2FA for the rest of the tenant.",
        )
    old_value = tenant.enforce_2fa
    tenant.enforce_2fa = payload.enabled
    session.add(
        AuditEvent(
            tenant_id=tenant_id,
            user_id=context.user_id,
            event_type="tenant_settings",
            scope="enforce_2fa",
            title=f"enforce_2fa changed from {old_value} to {payload.enabled}",
            prompt_type="enforce_2fa_toggle",
            tables_queried=[],
            documents_read=[],
        )
    )
    await session.commit()
    await session.refresh(tenant)
    return Enforce2faSettingsResponse(enabled=tenant.enforce_2fa)


@router.get(
    "/current/2fa-enforcement",
    response_model=Enforce2faSettingsResponse,
)
async def get_current_enforce_2fa(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> Enforce2faSettingsResponse:
    tenant = await session.get(Tenant, context.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return Enforce2faSettingsResponse(enabled=tenant.enforce_2fa)


@router.put(
    "/current/2fa-enforcement",
    response_model=Enforce2faSettingsResponse,
)
async def set_current_enforce_2fa(
    payload: Enforce2faSettingsUpdate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> Enforce2faSettingsResponse:
    """Toggle tenant-wide 2FA enforcement for the calling tenant."""
    return await _set_enforce_2fa(session, context, context.tenant_id, payload)


@router.get(
    "/{tenant_id}/2fa-enforcement",
    response_model=Enforce2faSettingsResponse,
)
async def get_enforce_2fa(
    tenant_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> Enforce2faSettingsResponse:
    """Return the tenant-wide 2FA enforcement flag."""
    if not context.is_service and context.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="Cannot access another tenant")
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return Enforce2faSettingsResponse(enabled=tenant.enforce_2fa)


@router.put(
    "/{tenant_id}/2fa-enforcement",
    response_model=Enforce2faSettingsResponse,
)
async def set_enforce_2fa(
    tenant_id: int,
    payload: Enforce2faSettingsUpdate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> Enforce2faSettingsResponse:
    """Toggle tenant-wide 2FA enforcement on or off.

    Tenant admins may toggle their own tenant; root/super admins may toggle any
    tenant.
    """
    if not context.is_service and context.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="Cannot modify another tenant")
    return await _set_enforce_2fa(session, context, tenant_id, payload)


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

