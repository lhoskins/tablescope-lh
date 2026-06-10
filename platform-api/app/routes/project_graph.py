"""Project Knowledge Graph API — nodes and edges for relationship mapping."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.database import get_db
from app.models.project import Project

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects/{project_id}/graph", tags=["project-graph"])


class GraphNodeRead(BaseModel):
    id: int
    type: str
    label: str
    source_type: str | None = None
    source_id: int | None = None
    properties: dict = {}


class GraphEdgeRead(BaseModel):
    id: int
    source: int  # from_node_id
    target: int  # to_node_id
    type: str
    confidence: float = 0.0
    evidence: str = ""


class GraphResponse(BaseModel):
    nodes: list[GraphNodeRead]
    edges: list[GraphEdgeRead]


async def _require_project_access(
    project_id: int, session: AsyncSession, context: RequestContext,
) -> Project:
    project = await session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=403, detail="Not in this tenant")
    return project


@router.get("", response_model=GraphResponse)
async def get_project_graph(
    project_id: int,
    node_id: int | None = None,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(),
):
    await _require_project_access(project_id, session, context)

    if node_id:
        # Get subgraph centered on a specific node
        nodes_result = await session.execute(
            text("""
                SELECT DISTINCT n.id, n.node_type, n.name, n.source_type, n.source_id, n.properties
                FROM ai_project_graph_nodes n
                LEFT JOIN ai_project_graph_edges e ON (n.id = e.from_node_id OR n.id = e.to_node_id)
                WHERE n.tenant_id=:tid AND n.project_id=:pid
                  AND (n.id=:nid OR e.from_node_id=:nid OR e.to_node_id=:nid)
            """),
            {"tid": context.tenant_id, "pid": project_id, "nid": node_id},
        )
    else:
        nodes_result = await session.execute(
            text("""
                SELECT id, node_type, name, source_type, source_id, properties
                FROM ai_project_graph_nodes
                WHERE tenant_id=:tid AND project_id=:pid
                ORDER BY id
            """),
            {"tid": context.tenant_id, "pid": project_id},
        )

    nodes = []
    node_ids = set()
    for row in nodes_result.fetchall():
        nid, ntype, name, stype, sid, props = row
        node_ids.add(nid)
        nodes.append(GraphNodeRead(
            id=nid, type=ntype, label=name,
            source_type=stype, source_id=sid,
            properties=props if isinstance(props, dict) else {},
        ))

    if not node_ids:
        return GraphResponse(nodes=[], edges=[])

    edges_result = await session.execute(
        text("""
            SELECT id, from_node_id, to_node_id, relationship_type, confidence, evidence
            FROM ai_project_graph_edges
            WHERE tenant_id=:tid AND project_id=:pid
        """),
        {"tid": context.tenant_id, "pid": project_id},
    )

    edges = []
    for row in edges_result.fetchall():
        eid, fid, tid_edge, etype, conf, ev = row
        if fid in node_ids and tid_edge in node_ids:
            ev_str = str(ev) if ev and not isinstance(ev, str) else (ev or "")
            edges.append(GraphEdgeRead(
                id=eid, source=fid, target=tid_edge,
                type=etype, confidence=float(conf or 0), evidence=ev_str,
            ))

    return GraphResponse(nodes=nodes, edges=edges)
