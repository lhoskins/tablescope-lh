"""API routes for AI asset metadata — tag/KPI suggestions and accepted values."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.ai_asset_metadata import (
    AIAssetKPI,
    AIAssetKPISuggestion,
    AIAssetTag,
    AIAssetTagSuggestion,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai/assets", tags=["ai-asset-metadata"])


# ── Get all metadata for an asset ─────────────────────────────────────────


@router.get("/{source_type}/{source_id}/metadata")
async def get_asset_metadata(
    source_type: str,
    source_id: int,
    project_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    tag_suggestions = (
        await session.scalars(
            select(AIAssetTagSuggestion).where(
                AIAssetTagSuggestion.tenant_id == context.tenant_id,
                AIAssetTagSuggestion.project_id == project_id,
                AIAssetTagSuggestion.source_type == source_type,
                AIAssetTagSuggestion.source_id == source_id,
            )
        )
    ).all()

    accepted_tags = (
        await session.scalars(
            select(AIAssetTag).where(
                AIAssetTag.tenant_id == context.tenant_id,
                AIAssetTag.project_id == project_id,
                AIAssetTag.source_type == source_type,
                AIAssetTag.source_id == source_id,
            )
        )
    ).all()

    kpi_suggestions = (
        await session.scalars(
            select(AIAssetKPISuggestion).where(
                AIAssetKPISuggestion.tenant_id == context.tenant_id,
                AIAssetKPISuggestion.project_id == project_id,
                AIAssetKPISuggestion.source_type == source_type,
                AIAssetKPISuggestion.source_id == source_id,
            )
        )
    ).all()

    accepted_kpis = (
        await session.scalars(
            select(AIAssetKPI).where(
                AIAssetKPI.tenant_id == context.tenant_id,
                AIAssetKPI.project_id == project_id,
                AIAssetKPI.source_type == source_type,
                AIAssetKPI.source_id == source_id,
            )
        )
    ).all()

    return {
        "tag_suggestions": [t.to_dict() for t in tag_suggestions],
        "accepted_tags": [t.to_dict() for t in accepted_tags],
        "kpi_suggestions": [k.to_dict() for k in kpi_suggestions],
        "accepted_kpis": [k.to_dict() for k in accepted_kpis],
    }


# ── Accept tags ────────────────────────────────────────────────────────────


class AcceptTagsRequest(BaseModel):
    project_id: int
    suggestion_ids: list[int] = []
    custom_tags: list[dict[str, Any]] = []


@router.post("/{source_type}/{source_id}/tags/accept")
async def accept_tags(
    source_type: str,
    source_id: int,
    body: AcceptTagsRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    accepted = []

    for sid in body.suggestion_ids:
        suggestion = await session.get(AIAssetTagSuggestion, sid)
        if not suggestion or suggestion.tenant_id != context.tenant_id:
            continue
        suggestion.status = "accepted"

        tag = AIAssetTag(
            tenant_id=context.tenant_id,
            project_id=body.project_id,
            source_type=source_type,
            source_id=source_id,
            tag_key=suggestion.tag_key,
            display_name=suggestion.display_name,
            confidence=suggestion.confidence,
            source="ai_suggested",
            created_by=context.user_id,
        )
        session.add(tag)
        accepted.append(suggestion.tag_key)

    for ct in body.custom_tags:
        tag = AIAssetTag(
            tenant_id=context.tenant_id,
            project_id=body.project_id,
            source_type=source_type,
            source_id=source_id,
            tag_key=ct["tag_key"],
            display_name=ct.get("display_name", ct["tag_key"]),
            business_domain=ct.get("business_domain"),
            process_area=ct.get("process_area"),
            source="user_created",
            created_by=context.user_id,
        )
        session.add(tag)
        accepted.append(ct["tag_key"])

    await session.commit()
    return {"accepted": accepted}


# ── Reject tags ────────────────────────────────────────────────────────────


class RejectSuggestionsRequest(BaseModel):
    suggestion_ids: list[int]


@router.post("/{source_type}/{source_id}/tags/reject")
async def reject_tags(
    source_type: str,
    source_id: int,
    body: RejectSuggestionsRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    rejected = []
    for sid in body.suggestion_ids:
        suggestion = await session.get(AIAssetTagSuggestion, sid)
        if not suggestion or suggestion.tenant_id != context.tenant_id:
            continue
        suggestion.status = "rejected"
        rejected.append(suggestion.tag_key)
    await session.commit()
    return {"rejected": rejected}


# ── Remove accepted tag ───────────────────────────────────────────────────


@router.delete("/{source_type}/{source_id}/tags/{tag_id}")
async def remove_accepted_tag(
    source_type: str,
    source_id: int,
    tag_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, str]:
    tag = await session.get(AIAssetTag, tag_id)
    if not tag or tag.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Tag not found")
    await session.delete(tag)
    await session.commit()
    return {"status": "deleted"}


# ── Accept KPIs ────────────────────────────────────────────────────────────


class AcceptKPIsRequest(BaseModel):
    project_id: int
    suggestion_ids: list[int] = []


@router.post("/{source_type}/{source_id}/kpis/accept")
async def accept_kpis(
    source_type: str,
    source_id: int,
    body: AcceptKPIsRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    accepted = []
    for sid in body.suggestion_ids:
        suggestion = await session.get(AIAssetKPISuggestion, sid)
        if not suggestion or suggestion.tenant_id != context.tenant_id:
            continue
        suggestion.status = "accepted"

        kpi = AIAssetKPI(
            tenant_id=context.tenant_id,
            project_id=body.project_id,
            source_type=source_type,
            source_id=source_id,
            kpi_key=suggestion.kpi_key,
            display_name=suggestion.display_name,
            field_mapping=suggestion.field_mapping,
            formula=suggestion.formula,
            recommended_chart_type=suggestion.recommended_chart_type,
            confidence=suggestion.confidence,
            source="ai_suggested",
            created_by=context.user_id,
        )
        session.add(kpi)
        accepted.append(suggestion.kpi_key)

    await session.commit()
    return {"accepted": accepted}


# ── Reject KPIs ────────────────────────────────────────────────────────────


@router.post("/{source_type}/{source_id}/kpis/reject")
async def reject_kpis(
    source_type: str,
    source_id: int,
    body: RejectSuggestionsRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    rejected = []
    for sid in body.suggestion_ids:
        suggestion = await session.get(AIAssetKPISuggestion, sid)
        if not suggestion or suggestion.tenant_id != context.tenant_id:
            continue
        suggestion.status = "rejected"
        rejected.append(suggestion.kpi_key)
    await session.commit()
    return {"rejected": rejected}


# ── Remove accepted KPI ──────────────────────────────────────────────────


@router.delete("/{source_type}/{source_id}/kpis/{kpi_id}")
async def remove_accepted_kpi(
    source_type: str,
    source_id: int,
    kpi_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, str]:
    kpi = await session.get(AIAssetKPI, kpi_id)
    if not kpi or kpi.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="KPI not found")
    await session.delete(kpi)
    await session.commit()
    return {"status": "deleted"}
