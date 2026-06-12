"""Reference catalog service — query governed tags and KPIs for AI context."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_reference_catalog import (
    AIReferenceCatalog,
    AIReferenceKPI,
    AIReferenceTag,
    TenantCustomKPI,
    TenantCustomTag,
    TenantReferenceCatalog,
)


async def get_enabled_catalogs(session: AsyncSession, tenant_id: int) -> list[dict[str, Any]]:
    """Return catalogs enabled for a tenant (or all system catalogs if none configured)."""
    enabled = (
        await session.scalars(
            select(TenantReferenceCatalog).where(
                TenantReferenceCatalog.tenant_id == tenant_id,
                TenantReferenceCatalog.is_enabled.is_(True),
            )
        )
    ).all()

    if enabled:
        catalog_ids = [e.catalog_id for e in enabled]
        catalogs = (
            await session.scalars(
                select(AIReferenceCatalog).where(
                    AIReferenceCatalog.id.in_(catalog_ids),
                    AIReferenceCatalog.is_active.is_(True),
                )
            )
        ).all()
    else:
        catalogs = (
            await session.scalars(
                select(AIReferenceCatalog).where(
                    AIReferenceCatalog.is_active.is_(True),
                    AIReferenceCatalog.is_system.is_(True),
                )
            )
        ).all()

    return [c.to_dict() for c in catalogs]


async def get_reference_tags(
    session: AsyncSession,
    tenant_id: int,
    catalog_id: int | None = None,
) -> list[dict[str, Any]]:
    """Return all governed tags from enabled catalogs + tenant custom tags."""
    catalogs = await get_enabled_catalogs(session, tenant_id)
    catalog_ids = [c["id"] for c in catalogs]
    if catalog_id:
        catalog_ids = [cid for cid in catalog_ids if cid == catalog_id]

    q = select(AIReferenceTag).where(
        AIReferenceTag.catalog_id.in_(catalog_ids),
        AIReferenceTag.is_active.is_(True),
    )
    ref_tags = (await session.scalars(q)).all()
    result = [t.to_dict() for t in ref_tags]

    custom = (
        await session.scalars(
            select(TenantCustomTag).where(
                TenantCustomTag.tenant_id == tenant_id,
                TenantCustomTag.is_active.is_(True),
            )
        )
    ).all()
    result.extend(t.to_dict() for t in custom)
    return result


async def get_reference_kpis(
    session: AsyncSession,
    tenant_id: int,
    catalog_id: int | None = None,
) -> list[dict[str, Any]]:
    """Return all governed KPIs from enabled catalogs + tenant custom KPIs."""
    catalogs = await get_enabled_catalogs(session, tenant_id)
    catalog_ids = [c["id"] for c in catalogs]
    if catalog_id:
        catalog_ids = [cid for cid in catalog_ids if cid == catalog_id]

    q = select(AIReferenceKPI).where(
        AIReferenceKPI.catalog_id.in_(catalog_ids),
        AIReferenceKPI.is_active.is_(True),
    )
    ref_kpis = (await session.scalars(q)).all()
    result = [k.to_dict() for k in ref_kpis]

    custom = (
        await session.scalars(
            select(TenantCustomKPI).where(
                TenantCustomKPI.tenant_id == tenant_id,
                TenantCustomKPI.is_active.is_(True),
            )
        )
    ).all()
    result.extend(k.to_dict() for k in custom)
    return result


async def search_tags(
    session: AsyncSession,
    tenant_id: int,
    query: str,
) -> list[dict[str, Any]]:
    """Full-text search across tag keys, names, synonyms."""
    all_tags = await get_reference_tags(session, tenant_id)
    q_lower = query.lower()
    results = []
    for tag in all_tags:
        if (
            q_lower in tag["tag_key"].lower()
            or q_lower in tag["display_name"].lower()
            or any(q_lower in s.lower() for s in tag.get("synonyms", []))
        ):
            results.append(tag)
    return results


async def search_kpis(
    session: AsyncSession,
    tenant_id: int,
    query: str,
) -> list[dict[str, Any]]:
    """Full-text search across KPI keys, names, related tags."""
    all_kpis = await get_reference_kpis(session, tenant_id)
    q_lower = query.lower()
    results = []
    for kpi in all_kpis:
        if (
            q_lower in kpi["kpi_key"].lower()
            or q_lower in kpi["display_name"].lower()
            or any(q_lower in t.lower() for t in kpi.get("related_tags", []))
        ):
            results.append(kpi)
    return results


async def get_tags_and_kpis_for_ai_prompt(
    session: AsyncSession,
    tenant_id: int,
) -> dict[str, Any]:
    """Compact representation of tags + KPIs suitable for AI prompt injection."""
    tags = await get_reference_tags(session, tenant_id)
    kpis = await get_reference_kpis(session, tenant_id)

    tag_list = [
        {
            "tag_key": t["tag_key"],
            "display_name": t["display_name"],
            "business_domain": t.get("business_domain"),
            "process_area": t.get("process_area"),
            "synonyms": t.get("synonyms", []),
            "example_fields": t.get("example_fields", []),
        }
        for t in tags
    ]
    kpi_list = [
        {
            "kpi_key": k["kpi_key"],
            "display_name": k["display_name"],
            "business_domain": k.get("business_domain"),
            "formula": k.get("formula"),
            "required_fields": k.get("required_fields", []),
            "related_tags": k.get("related_tags", []),
            "recommended_chart_type": k.get("recommended_chart_type"),
        }
        for k in kpis
    ]
    return {"reference_tags": tag_list, "reference_kpis": kpi_list}
