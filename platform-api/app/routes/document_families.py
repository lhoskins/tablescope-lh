"""Document Family API — list, detail, members, accept/change/remove, summary.

Families live in the project knowledge graph (node_type='document_family'). These
endpoints expose them to the UI and let users curate auto-detected families.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.config import get_settings
from app.database import get_db
from app.models.project import Project
from app.models.project_asset import ProjectAsset
from app.services.project_graph_service import (
    _as_dict,
    archive_empty_family,
    deactivate_document_edges,
    get_family_members,
    get_family_node,
    link_document_to_family,
    log_family_event,
    normalize_family_key,
    upsert_document_family_node,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects/{project_id}", tags=["document-families"])


# ── Schemas ──────────────────────────────────────────────────────────

class FamilySummary(BaseModel):
    family_node_id: int
    family_name: str
    family_key: str
    family_type: str
    business_domain: str
    member_count: int
    document_count: int
    datasource_count: int
    kpi_count: int
    summary: str = ""
    confidence: float = 0.0


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


# ── Helpers ──────────────────────────────────────────────────────────

async def _require_project(project_id: int, session: AsyncSession, context: RequestContext) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=403, detail="Not in this tenant")
    return project


async def _require_asset(
    project_id: int, asset_id: int, session: AsyncSession, context: RequestContext,
) -> ProjectAsset:
    asset = await session.get(ProjectAsset, asset_id)
    if not asset or asset.project_id != project_id or asset.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset


async def _get_or_create_document_node(
    session: AsyncSession, tenant_id: int, project_id: int, asset: ProjectAsset, created_by: int,
) -> int:
    result = await session.execute(
        text(
            """
            SELECT id FROM ai_project_graph_nodes
            WHERE tenant_id=:tid AND project_id=:pid
              AND source_type='project_asset' AND source_id=:sid
            ORDER BY id LIMIT 1
            """
        ),
        {"tid": tenant_id, "pid": project_id, "sid": asset.id},
    )
    row = result.fetchone()
    if row:
        await session.execute(
            text("UPDATE ai_project_graph_nodes SET is_active=true WHERE id=:id"),
            {"id": row[0]},
        )
        return row[0]

    meta = asset.ai_metadata if isinstance(asset.ai_metadata, dict) else {}
    props = {
        "summary": meta.get("summary", asset.ai_summary or ""),
        "document_type": meta.get("document_type", ""),
        "filename": asset.filename,
        "asset_type": asset.asset_type,
    }
    ins = await session.execute(
        text(
            """
            INSERT INTO ai_project_graph_nodes
                (tenant_id, project_id, node_type, source_type, source_id, name,
                 properties, visibility, is_active, created_by)
            VALUES (:tid, :pid, 'document', 'project_asset', :sid, :nm, :props,
                    'shared_project', true, :uid)
            RETURNING id
            """
        ),
        {
            "tid": tenant_id, "pid": project_id, "sid": asset.id,
            "nm": asset.filename, "props": json.dumps(props), "uid": created_by,
        },
    )
    out = ins.fetchone()
    if not out:
        raise HTTPException(status_code=500, detail="Could not create document node")
    return out[0]


async def _count_documents(session: AsyncSession, tenant_id: int, project_id: int, family_node_id: int) -> int:
    result = await session.execute(
        text(
            """
            SELECT COUNT(*) FROM ai_project_graph_edges e
            JOIN ai_project_graph_nodes n ON n.id = e.from_node_id
            WHERE e.tenant_id=:tid AND e.project_id=:pid AND e.to_node_id=:famid
              AND e.relationship_type='belongs_to_family'
              AND e.is_active=true AND n.is_active=true
            """
        ),
        {"tid": tenant_id, "pid": project_id, "famid": family_node_id},
    )
    return int(result.scalar() or 0)


# ── List / detail / members ──────────────────────────────────────────

@router.get("/document-families", response_model=list[FamilySummary])
async def list_document_families(
    project_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
):
    await _require_project(project_id, session, context)
    result = await session.execute(
        text(
            """
            SELECT id, name, properties FROM ai_project_graph_nodes
            WHERE tenant_id=:tid AND project_id=:pid
              AND node_type='document_family' AND is_active=true
            ORDER BY name
            """
        ),
        {"tid": context.tenant_id, "pid": project_id},
    )
    out: list[FamilySummary] = []
    for nid, name, props in result.fetchall():
        p = _as_dict(props)
        members = await get_family_members(session, context.tenant_id, project_id, nid)
        doc_count = len(members["documents"])
        ds_count = len(members["datasources"])
        kpi_count = len(members["kpis"])
        member_total = sum(len(v) for v in members.values())
        out.append(FamilySummary(
            family_node_id=nid,
            family_name=name,
            family_key=p.get("family_key", normalize_family_key(name)),
            family_type=p.get("family_type", ""),
            business_domain=p.get("business_domain", ""),
            member_count=member_total,
            document_count=doc_count,
            datasource_count=ds_count,
            kpi_count=kpi_count,
            summary=p.get("family_summary", p.get("description", "")),
            confidence=float(p.get("confidence", 0) or 0),
        ))
    return out


@router.get("/document-families/{family_node_id}")
async def get_document_family(
    project_id: int,
    family_node_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
):
    await _require_project(project_id, session, context)
    node = await get_family_node(session, context.tenant_id, project_id, family_node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Family not found")
    p = node["properties"]
    members = await get_family_members(session, context.tenant_id, project_id, family_node_id)
    # Build a relationships list from member documents' typed edges.
    relationships = await _family_relationships(session, context.tenant_id, project_id, family_node_id)
    return {
        "family_node_id": node["id"],
        "family_name": node["name"],
        "family_type": p.get("family_type", ""),
        "business_domain": p.get("business_domain", ""),
        "summary": p.get("family_summary", p.get("description", "")),
        "supported_kpis": p.get("supported_kpis", []),
        "related_processes": p.get("related_processes", []),
        "suggested_dashboards": p.get("suggested_dashboards", []),
        "missing_documents": p.get("missing_documents", []),
        "members": members,
        "relationships": relationships,
        "suggested_questions": p.get("suggested_questions", []),
    }


@router.get("/document-families/{family_node_id}/members")
async def get_document_family_members(
    project_id: int,
    family_node_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
):
    await _require_project(project_id, session, context)
    node = await get_family_node(session, context.tenant_id, project_id, family_node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Family not found")
    return await get_family_members(session, context.tenant_id, project_id, family_node_id)


async def _family_relationships(
    session: AsyncSession, tenant_id: int, project_id: int, family_node_id: int,
) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(
            """
            SELECT d.name AS from_name, e.relationship_type, t.name AS to_name,
                   e.confidence
            FROM ai_project_graph_edges fe
            JOIN ai_project_graph_nodes d ON d.id = fe.from_node_id
            JOIN ai_project_graph_edges e ON e.from_node_id = d.id
            JOIN ai_project_graph_nodes t ON t.id = e.to_node_id
            WHERE fe.tenant_id=:tid AND fe.project_id=:pid AND fe.to_node_id=:famid
              AND fe.relationship_type='belongs_to_family' AND fe.is_active=true
              AND e.relationship_type<>'belongs_to_family' AND e.is_active=true
              AND t.node_type NOT IN ('tag') AND t.is_active=true
            ORDER BY e.confidence DESC NULLS LAST
            LIMIT 200
            """
        ),
        {"tid": tenant_id, "pid": project_id, "famid": family_node_id},
    )
    return [
        {
            "from": fn, "relationship_type": rt, "to": tn,
            "confidence": float(conf or 0),
        }
        for fn, rt, tn, conf in rows.fetchall()
    ]


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
    suggested = meta.get("document_family") if isinstance(meta.get("document_family"), dict) else {}

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
    if meta.get("document_family"):
        new_meta = dict(meta)
        new_meta["document_family"] = None
        asset.ai_metadata = new_meta

    log_family_event(
        "document_family_removed",
        tenant_id=context.tenant_id, project_id=project_id, asset_id=asset_id,
        user_id=context.user_id,
    )
    await session.commit()
    return {"status": "removed", "asset_id": asset_id}


# ── Rebuild summary ──────────────────────────────────────────────────

@router.post("/document-families/{family_node_id}/rebuild-summary")
async def rebuild_family_summary(
    project_id: int,
    family_node_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
):
    await _require_project(project_id, session, context)
    node = await get_family_node(session, context.tenant_id, project_id, family_node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Family not found")

    members = await get_family_members(session, context.tenant_id, project_id, family_node_id)
    relationships = await _family_relationships(session, context.tenant_id, project_id, family_node_id)
    p = node["properties"]

    summary_data = await _call_family_summarize(
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        project_id=project_id,
        family_name=node["name"],
        family_type=p.get("family_type", ""),
        business_domain=p.get("business_domain", ""),
        members=members,
        relationships=relationships,
    )
    if summary_data is None:
        raise HTTPException(status_code=502, detail="Family summarization is unavailable")

    new_props = dict(p)
    new_props["family_summary"] = summary_data.get("summary", "")
    new_props["primary_purpose"] = summary_data.get("primary_purpose", "")
    new_props["supported_kpis"] = summary_data.get("supported_kpis", [])
    new_props["related_processes"] = summary_data.get("related_processes", [])
    new_props["suggested_dashboards"] = summary_data.get("suggested_dashboards", [])
    new_props["missing_documents"] = summary_data.get("missing_documents", [])
    new_props["suggested_questions"] = summary_data.get("suggested_questions", [])
    new_props["updated_at"] = time.time()

    await session.execute(
        text("UPDATE ai_project_graph_nodes SET properties=:p WHERE id=:id"),
        {"p": json.dumps(new_props), "id": family_node_id},
    )
    log_family_event(
        "document_family_summary_rebuilt",
        tenant_id=context.tenant_id, project_id=project_id,
        family_node_id=family_node_id, user_id=context.user_id,
    )
    await session.commit()
    return {"status": "rebuilt", "family_node_id": family_node_id, **summary_data}


async def _call_family_summarize(
    tenant_id: int,
    user_id: int,
    project_id: int,
    family_name: str,
    family_type: str,
    business_domain: str,
    members: dict[str, list[dict[str, Any]]],
    relationships: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Call the dedicated /ai/family/summarize endpoint. Returns None on failure."""
    settings = get_settings()
    if not settings.tablescope_ai_enabled or not settings.tablescope_ai_api_url:
        return None

    payload: dict[str, Any] = {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "project_id": project_id,
        "family_name": family_name,
        "family_type": family_type,
        "business_domain": business_domain,
        "member_documents": [
            {"name": d["name"], "summary": d.get("summary", "")}
            for d in members.get("documents", [])
        ],
        "member_datasources": [{"name": d["name"]} for d in members.get("datasources", [])],
        "member_kpis": [d["name"] for d in members.get("kpis", [])],
        "member_entities": [d["name"] for d in members.get("entities", [])],
        "relationships": relationships,
        "timestamp": time.time(),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["signature"] = hmac.new(
        settings.tablescope_ai_signing_secret.encode(),
        canonical.encode(),
        hashlib.sha256,
    ).hexdigest()

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{settings.tablescope_ai_api_url}/ai/family/summarize", json=payload,
            )
        if resp.status_code != 200:
            logger.warning("family/summarize HTTP %d: %s", resp.status_code, resp.text[:200])
            return None
        return resp.json()
    except Exception as exc:
        logger.warning("family/summarize failed: %s", exc)
        return None
