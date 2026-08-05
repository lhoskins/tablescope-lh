"""Tenant self-service settings: current tenant view and company branding.

Split from ``tenants.py``; siblings: ``tenants_crud.py``,
``tenants_security_policy.py`` and ``tenants_users.py``.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.membership import require_membership
from app.auth.rbac import Role, require_role
from app.config import get_settings
from app.database import get_db
from app.models.tenant import Tenant
from app.schemas.tenant import CompanyLogoRead, TenantRead, TenantSettingsRead
from app.services.company_logo_storage import (
    CompanyLogoValidationError,
    read_company_logo,
    store_company_logo,
    validate_company_logo,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.get("/me", response_model=TenantRead)
async def get_my_tenant(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_membership),
) -> TenantRead:
    tenant = await session.get(Tenant, context.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return TenantRead.model_validate(tenant)


def _tenant_login_url(tenant: Tenant) -> str:
    base = get_settings().app_base_url.rstrip("/")
    return f"{base}/{tenant.slug}/login"


@router.get("/current/settings", response_model=TenantSettingsRead)
async def get_current_tenant_settings(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> TenantSettingsRead:
    """Return a safe, tenant-facing view of the current tenant.

    Excludes users, VDB assignments, VDB health, locations, credentials, and
    other platform metadata.
    """
    tenant = await session.get(Tenant, context.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    data = TenantRead.model_validate(tenant).model_dump(mode="json")
    data["allowed_domains_enabled"] = tenant.allowed_domains_enabled
    return TenantSettingsRead(**data, login_url=_tenant_login_url(tenant))


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

