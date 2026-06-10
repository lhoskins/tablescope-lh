"""API routes for the AI reference catalog — tags, KPIs, tenant customization."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.ai_reference_catalog import (
    AIReferenceCatalog,
    TenantCustomKPI,
    TenantCustomTag,
    TenantReferenceCatalog,
)
from app.services.reference_catalog_service import (
    get_enabled_catalogs,
    get_reference_kpis,
    get_reference_tags,
    search_kpis,
    search_tags,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai/reference", tags=["ai-reference"])


# ── List catalogs ──────────────────────────────────────────────────────────


@router.get("/catalogs")
async def list_catalogs(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[dict[str, Any]]:
    return await get_enabled_catalogs(session, context.tenant_id)


# ── List tags ──────────────────────────────────────────────────────────────


@router.get("/tags")
async def list_tags(
    catalog_id: int | None = Query(None),
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[dict[str, Any]]:
    return await get_reference_tags(session, context.tenant_id, catalog_id=catalog_id)


# ── List KPIs ──────────────────────────────────────────────────────────────


@router.get("/kpis")
async def list_kpis(
    catalog_id: int | None = Query(None),
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[dict[str, Any]]:
    return await get_reference_kpis(session, context.tenant_id, catalog_id=catalog_id)


# ── Search ─────────────────────────────────────────────────────────────────


@router.get("/search")
async def search_catalog(
    query: str = Query(..., min_length=1),
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    tags = await search_tags(session, context.tenant_id, query)
    kpis = await search_kpis(session, context.tenant_id, query)
    return {"tags": tags, "kpis": kpis}


# ── Tenant catalog enablement ─────────────────────────────────────────────


class CatalogToggleRequest(BaseModel):
    catalog_id: int
    is_enabled: bool


@router.post("/tenant-catalogs")
async def toggle_tenant_catalog(
    body: CatalogToggleRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> dict[str, Any]:
    catalog = await session.get(AIReferenceCatalog, body.catalog_id)
    if not catalog:
        raise HTTPException(status_code=404, detail="Catalog not found")

    existing = await session.scalar(
        select(TenantReferenceCatalog).where(
            TenantReferenceCatalog.tenant_id == context.tenant_id,
            TenantReferenceCatalog.catalog_id == body.catalog_id,
        )
    )
    if existing:
        existing.is_enabled = body.is_enabled
    else:
        session.add(
            TenantReferenceCatalog(
                tenant_id=context.tenant_id,
                catalog_id=body.catalog_id,
                is_enabled=body.is_enabled,
            )
        )
    await session.commit()
    return {"status": "ok", "catalog_id": body.catalog_id, "is_enabled": body.is_enabled}


# ── Tenant custom tags ────────────────────────────────────────────────────


class CreateCustomTagRequest(BaseModel):
    tag_key: str
    display_name: str
    description: str | None = None
    business_domain: str | None = None
    process_area: str | None = None
    synonyms: list[str] = []


@router.post("/tenant-tags")
async def create_tenant_tag(
    body: CreateCustomTagRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> dict[str, Any]:
    tag = TenantCustomTag(
        tenant_id=context.tenant_id,
        tag_key=body.tag_key,
        display_name=body.display_name,
        description=body.description,
        business_domain=body.business_domain,
        process_area=body.process_area,
        synonyms=body.synonyms,
        created_by=context.user_id,
    )
    session.add(tag)
    await session.commit()
    return tag.to_dict()


@router.patch("/tenant-tags/{tag_id}")
async def update_tenant_tag(
    tag_id: int,
    body: CreateCustomTagRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> dict[str, Any]:
    tag = await session.get(TenantCustomTag, tag_id)
    if not tag or tag.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Tag not found")
    tag.tag_key = body.tag_key
    tag.display_name = body.display_name
    tag.description = body.description
    tag.business_domain = body.business_domain
    tag.process_area = body.process_area
    tag.synonyms = body.synonyms
    await session.commit()
    return tag.to_dict()


# ── Tenant custom KPIs ────────────────────────────────────────────────────


class CreateCustomKPIRequest(BaseModel):
    kpi_key: str
    display_name: str
    description: str | None = None
    business_domain: str | None = None
    process_area: str | None = None
    formula: str | None = None
    required_fields: list[str] = []
    optional_fields: list[str] = []
    related_tags: list[str] = []
    recommended_chart_type: str | None = None


@router.post("/tenant-kpis")
async def create_tenant_kpi(
    body: CreateCustomKPIRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> dict[str, Any]:
    kpi = TenantCustomKPI(
        tenant_id=context.tenant_id,
        kpi_key=body.kpi_key,
        display_name=body.display_name,
        description=body.description,
        business_domain=body.business_domain,
        process_area=body.process_area,
        formula=body.formula,
        required_fields=body.required_fields,
        optional_fields=body.optional_fields,
        related_tags=body.related_tags,
        recommended_chart_type=body.recommended_chart_type,
        created_by=context.user_id,
    )
    session.add(kpi)
    await session.commit()
    return kpi.to_dict()


@router.patch("/tenant-kpis/{kpi_id}")
async def update_tenant_kpi(
    kpi_id: int,
    body: CreateCustomKPIRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> dict[str, Any]:
    kpi = await session.get(TenantCustomKPI, kpi_id)
    if not kpi or kpi.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="KPI not found")
    kpi.kpi_key = body.kpi_key
    kpi.display_name = body.display_name
    kpi.description = body.description
    kpi.business_domain = body.business_domain
    kpi.process_area = body.process_area
    kpi.formula = body.formula
    kpi.required_fields = body.required_fields
    kpi.optional_fields = body.optional_fields
    kpi.related_tags = body.related_tags
    kpi.recommended_chart_type = body.recommended_chart_type
    await session.commit()
    return kpi.to_dict()
