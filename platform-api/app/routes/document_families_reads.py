"""Document Family reads — list, detail and members.

Families live in the project knowledge graph (node_type='document_family').
This module also hosts the shared access-check helpers used by the sibling
document-family route modules.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.project import Project
from app.models.project_asset import ProjectAsset
from app.services.project_graph_service import (
    _as_dict,
    get_family_members,
    get_family_node,
    normalize_family_key,
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
