"""Document Family curation — accept, change and remove a document's family."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.routes.document_families_reads import (
    _get_or_create_document_node,
    _require_asset,
    _require_project,
)
from app.services.ai_confidence_audit import record_ai_confidence_decision
from app.services.project_graph_service import (
    archive_empty_family,
    deactivate_document_edges,
    link_document_to_family,
    log_family_event,
    normalize_family_key,
    upsert_document_family_node,
)

_CONFIDENCE_SOURCE_PIPELINE = "document_family"


def _ai_confidence(meta: dict) -> float | None:
    """The AI-suggested confidence recorded on this asset, if any -- read
    before the decision below overwrites ``document_family`` on ``meta``.
    """
    suggested = meta.get("document_family")
    if not isinstance(suggested, dict):
        return None
    conf = suggested.get("confidence")
    try:
        return float(conf) if conf is not None else None
    except (TypeError, ValueError):
        return None

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects/{project_id}", tags=["document-families"])


# ── Schemas ──────────────────────────────────────────────────────────

class AcceptFamilyRequest(BaseModel):
    family_name: str | None = None
    family_key: str | None = None
    family_type: str | None = None
    role: str | None = None
    confidence: float | None = None
    reason: str | None = None


class ChangeFamilyRequest(BaseModel):
    family_name: str
    family_type: str | None = None
    role: str | None = None
    confidence: float | None = None
    reason: str | None = None


# ── Accept / change / remove ─────────────────────────────────────────

@router.post("/assets/{asset_id}/family/accept")
async def accept_family(
    project_id: int,
    asset_id: int,
    body: AcceptFamilyRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
):
    await _require_project(project_id, session, context)
    asset = await _require_asset(project_id, asset_id, session, context)

    meta = asset.ai_metadata if isinstance(asset.ai_metadata, dict) else {}
    suggested_raw = meta.get("document_family")
    suggested: dict[str, Any] = suggested_raw if isinstance(suggested_raw, dict) else {}
    ai_confidence_at_decision = _ai_confidence(meta)

    family_name = (body.family_name or suggested.get("family_name") or "").strip()
    if not family_name:
        raise HTTPException(status_code=400, detail="No family to accept (no suggestion and none provided)")
    family_key = (body.family_key or suggested.get("family_key") or normalize_family_key(family_name)).strip().lower()
    family_type = (body.family_type or suggested.get("family_type") or "general_knowledge_group")
    role = (body.role or suggested.get("role") or "unknown")
    reason = body.reason or suggested.get("reason") or "User accepted suggested family."
    confidence = body.confidence if body.confidence is not None else float(suggested.get("confidence", 0.7) or 0.7)
    business_domain = str(meta.get("business_domain", "")).strip()

    doc_node_id = await _get_or_create_document_node(
        session, context.tenant_id, project_id, asset, context.user_id,
    )
    family_node_id = await upsert_document_family_node(
        session, context.tenant_id, project_id, family_name, family_key, family_type,
        business_domain, confidence, reason, context.user_id,
    )
    if not family_node_id:
        raise HTTPException(status_code=500, detail="Could not create family")
    await link_document_to_family(
        session, context.tenant_id, project_id, doc_node_id, family_node_id,
        confidence, reason, context.user_id, role=role,
    )

    # Mark the suggestion as accepted in ai_metadata.
    new_meta = dict(meta)
    new_meta["document_family"] = {
        "family_name": family_name, "family_key": family_key,
        "family_type": family_type, "confidence": confidence, "role": role,
        "reason": reason, "auto_link": True,
    }
    asset.ai_metadata = new_meta

    log_family_event(
        "document_family_accepted",
        tenant_id=context.tenant_id, project_id=project_id, asset_id=asset_id,
        family_node_id=family_node_id, family_name=family_name,
        confidence=confidence, action_source="user_accept", user_id=context.user_id,
    )
    await record_ai_confidence_decision(
        session, tenant_id=context.tenant_id, project_id=project_id, asset_id=asset_id,
        source_pipeline=_CONFIDENCE_SOURCE_PIPELINE,
        ai_confidence_at_decision=ai_confidence_at_decision,
        human_decision="accepted", decided_by=context.user_id,
    )
    await session.commit()
    return {"status": "accepted", "family_node_id": family_node_id, "family_name": family_name}


@router.post("/assets/{asset_id}/family/change")
async def change_family(
    project_id: int,
    asset_id: int,
    body: ChangeFamilyRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
):
    await _require_project(project_id, session, context)
    asset = await _require_asset(project_id, asset_id, session, context)

    family_name = body.family_name.strip()
    if not family_name:
        raise HTTPException(status_code=400, detail="family_name is required")
    family_key = normalize_family_key(family_name)
    family_type = body.family_type or "general_knowledge_group"
    role = body.role or "unknown"
    reason = body.reason or "User moved document to another family."
    confidence = body.confidence if body.confidence is not None else 1.0
    meta = asset.ai_metadata if isinstance(asset.ai_metadata, dict) else {}
    ai_confidence_at_decision = _ai_confidence(meta)
    business_domain = str(meta.get("business_domain", "")).strip()

    doc_node_id = await _get_or_create_document_node(
        session, context.tenant_id, project_id, asset, context.user_id,
    )
    # Capture old families to archive any that become empty.
    old_family_ids = await deactivate_document_edges(
        session, context.tenant_id, project_id, doc_node_id,
    )

    family_node_id = await upsert_document_family_node(
        session, context.tenant_id, project_id, family_name, family_key, family_type,
        business_domain, confidence, reason, context.user_id,
    )
    if not family_node_id:
        raise HTTPException(status_code=500, detail="Could not create family")
    await link_document_to_family(
        session, context.tenant_id, project_id, doc_node_id, family_node_id,
        confidence, reason, context.user_id, role=role,
    )
    for fid in old_family_ids:
        if fid != family_node_id:
            await archive_empty_family(session, context.tenant_id, project_id, fid)

    new_meta = dict(meta)
    new_meta["document_family"] = {
        "family_name": family_name, "family_key": family_key,
        "family_type": family_type, "confidence": confidence, "role": role,
        "reason": reason, "auto_link": True,
    }
    asset.ai_metadata = new_meta

    log_family_event(
        "document_family_changed",
        tenant_id=context.tenant_id, project_id=project_id, asset_id=asset_id,
        family_node_id=family_node_id, family_name=family_name,
        action_source="user_change", user_id=context.user_id,
    )
    await record_ai_confidence_decision(
        session, tenant_id=context.tenant_id, project_id=project_id, asset_id=asset_id,
        source_pipeline=_CONFIDENCE_SOURCE_PIPELINE,
        ai_confidence_at_decision=ai_confidence_at_decision,
        human_decision="changed", decided_by=context.user_id,
    )
    await session.commit()
    return {"status": "changed", "family_node_id": family_node_id, "family_name": family_name}


@router.delete("/assets/{asset_id}/family")
async def remove_family(
    project_id: int,
    asset_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
):
    await _require_project(project_id, session, context)
    asset = await _require_asset(project_id, asset_id, session, context)

    result = await session.execute(
        text(
            """
            SELECT id FROM ai_project_graph_nodes
            WHERE tenant_id=:tid AND project_id=:pid
              AND source_type='project_asset' AND source_id=:sid
            ORDER BY id LIMIT 1
            """
        ),
        {"tid": context.tenant_id, "pid": project_id, "sid": asset_id},
    )
    row = result.fetchone()
    affected: list[int] = []
    if row:
        affected = await deactivate_document_edges(session, context.tenant_id, project_id, row[0])
        for fid in affected:
            await archive_empty_family(session, context.tenant_id, project_id, fid)

    meta = asset.ai_metadata if isinstance(asset.ai_metadata, dict) else {}
    ai_confidence_at_decision = _ai_confidence(meta)
    if meta.get("document_family"):
        new_meta = dict(meta)
        new_meta["document_family"] = None
        asset.ai_metadata = new_meta

    log_family_event(
        "document_family_removed",
        tenant_id=context.tenant_id, project_id=project_id, asset_id=asset_id,
        user_id=context.user_id,
    )
    await record_ai_confidence_decision(
        session, tenant_id=context.tenant_id, project_id=project_id, asset_id=asset_id,
        source_pipeline=_CONFIDENCE_SOURCE_PIPELINE,
        ai_confidence_at_decision=ai_confidence_at_decision,
        human_decision="removed", decided_by=context.user_id,
    )
    await session.commit()
    return {"status": "removed", "asset_id": asset_id}
