"""Project Knowledge Graph API — nodes and edges for relationship mapping."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.services.knowledge_graph.visibility import _hidden_project_asset_ids
from app.services.project_access import authorize_project_access

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


class NodeCentricGraphResponse(BaseModel):
    """Extended node-centric Knowledge Graph payload.

    Keeps ``nodes``/``edges`` (backward compatible) and adds the insight-first
    fields: the selected center node, AI Home-style insight cards, gap findings,
    recommended actions, trace paths and stats.
    """

    model_config = {"extra": "allow"}

    centerNode: dict | None = None
    nodes: list[dict] = []
    edges: list[dict] = []
    insightCards: list[dict] = []
    gaps: list[dict] = []
    recommendedActions: list[dict] = []
    tracePaths: list[dict] = []
    stats: dict = {}
    pipeline_version: str = ""
    generated_at: str = ""


async def _require_project_access(
    project_id: int, session: AsyncSession, context: RequestContext,
):
    """Real project membership (owner or active ProjectMember), not just a
    tenant match -- see app.services.project_access. A tenant match alone let
    any same-tenant user, including non-members of a private project, read
    its Knowledge Graph."""
    return await authorize_project_access(
        session, tenant_id=context.tenant_id, user_id=context.user_id,
        project_id=project_id,
    )


FAMILY_NODE_TYPES = {"document_family"}
FAMILY_EDGE_TYPES = {
    "belongs_to_family", "governs", "responds_to", "supersedes", "superseded_by",
    "depends_on", "implements", "references", "exception_to", "procedure_for",
    "policy_for", "evidence_for", "supports", "contradicts", "updates",
    "appendix_to", "template_for", "meeting_notes_for", "postmortem_for",
    "remediation_for", "audit_evidence_for", "related_family_member",
    "measures_process", "incident_impact",
}


@router.get("")
async def get_project_graph(
    project_id: int,
    node_id: int | None = None,
    family_id: int | None = None,
    asset_id: int | None = None,
    include_families: bool = True,
    lens: str | None = None,
    center_node: str | None = None,
    min_confidence: float = 0.70,
    include_inferred: bool = False,
    # Connector-style policy toggles (see knowledge_graph_builder). Explicit and
    # inferred edges show by default; recommended (dashed) and weak (faint) edges
    # are opt-in. Enabling either widens the returned edge set so the frontend
    # can render and toggle them by ``relationshipStrength``.
    show_explicit: bool = True,
    show_inferred: bool = True,
    show_recommended: bool = False,
    show_weak: bool = False,
    severity: str = "all",
    refresh: bool = False,  # rebuild the cached snapshot instead of reading it
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
):
    await _require_project_access(project_id, session, context)

    # Recommended/weak connectors live below the default confidence floor, so
    # asking for them implies the wider (inferred) edge set.
    include_inferred = include_inferred or show_recommended or show_weak

    # Node-centric Insight-First Knowledge Graph: any new-UI caller passes a
    # ``lens`` (or a ``center_node``). Legacy callers (no new params) keep the
    # original full-graph ``{nodes, edges}`` response untouched.
    if lens is not None or center_node is not None or refresh:
        from app.services.knowledge_graph_builder import build_node_centric_graph
        return await build_node_centric_graph(
            session,
            tenant_id=context.tenant_id,
            project_id=project_id,
            user_id=context.user_id,
            role=context.role,
            center_node=center_node,
            lens=lens or "insight-first",
            min_confidence=min_confidence,
            include_inferred=include_inferred,
            severity=severity,
            refresh=refresh,
        )

    # asset_id is a convenience: resolve it to the asset's document node and
    # center the subgraph there.
    center_id = node_id or family_id
    if center_id is None and asset_id is not None:
        res = await session.execute(
            text("""
                SELECT id FROM ai_project_graph_nodes
                WHERE tenant_id=:tid AND project_id=:pid
                  AND source_type='project_asset' AND source_id=:sid AND is_active=true
                ORDER BY id LIMIT 1
            """),
            {"tid": context.tenant_id, "pid": project_id, "sid": asset_id},
        )
        row = res.fetchone()
        if row:
            center_id = row[0]
        else:
            return GraphResponse(nodes=[], edges=[])

    if center_id is not None:
        # Get subgraph centered on a specific node
        nodes_result = await session.execute(
            text("""
                SELECT DISTINCT n.id, n.node_type, n.name, n.source_type, n.source_id, n.properties
                FROM ai_project_graph_nodes n
                LEFT JOIN ai_project_graph_edges e
                  ON (n.id = e.from_node_id OR n.id = e.to_node_id) AND e.is_active=true
                WHERE n.tenant_id=:tid AND n.project_id=:pid AND n.is_active=true
                  AND (n.id=:nid OR e.from_node_id=:nid OR e.to_node_id=:nid)
            """),
            {"tid": context.tenant_id, "pid": project_id, "nid": center_id},
        )
    else:
        nodes_result = await session.execute(
            text("""
                SELECT id, node_type, name, source_type, source_id, properties
                FROM ai_project_graph_nodes
                WHERE tenant_id=:tid AND project_id=:pid AND is_active=true
                ORDER BY id
            """),
            {"tid": context.tenant_id, "pid": project_id},
        )

    raw_rows = [
        {"id": r[0], "node_type": r[1], "name": r[2], "source_type": r[3], "source_id": r[4], "properties": r[5]}
        for r in nodes_result.fetchall()
    ]
    # KG-04: a private document is only for its owner (and tenant admins),
    # even though every project member can otherwise read this graph.
    hidden_asset_ids = await _hidden_project_asset_ids(
        session, raw_rows, tenant_id=context.tenant_id,
        user_id=context.user_id, role=context.role,
    )

    nodes = []
    node_ids = set()
    for nrow in raw_rows:
        if not include_families and nrow["node_type"] in FAMILY_NODE_TYPES:
            continue
        if nrow["source_type"] == "project_asset" and nrow["source_id"] in hidden_asset_ids:
            continue
        node_ids.add(nrow["id"])
        nodes.append(GraphNodeRead(
            id=nrow["id"], type=nrow["node_type"], label=nrow["name"],
            source_type=nrow["source_type"], source_id=nrow["source_id"],
            properties=nrow["properties"] if isinstance(nrow["properties"], dict) else {},
        ))

    if not node_ids:
        return GraphResponse(nodes=[], edges=[])

    edges_result = await session.execute(
        text("""
            SELECT id, from_node_id, to_node_id, relationship_type, confidence, evidence
            FROM ai_project_graph_edges
            WHERE tenant_id=:tid AND project_id=:pid AND is_active=true
        """),
        {"tid": context.tenant_id, "pid": project_id},
    )

    edges = []
    for row in edges_result.fetchall():
        eid, fid, tid_edge, etype, conf, ev = row
        if not include_families and etype in FAMILY_EDGE_TYPES:
            continue
        if fid in node_ids and tid_edge in node_ids:
            ev_str = str(ev) if ev and not isinstance(ev, str) else (ev or "")
            edges.append(GraphEdgeRead(
                id=eid, source=fid, target=tid_edge,
                type=etype, confidence=float(conf or 0), evidence=ev_str,
            ))

    return GraphResponse(nodes=nodes, edges=edges)


@router.post("/refresh")
async def refresh_project_graph(
    project_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
):
    """Rebuild and persist the project's Knowledge Graph snapshot.

    Mirrors AI Home's manual refresh: collects the structural Evidence graph and
    re-runs AI enrichment for the default view, then caches the result so node
    clicks read from it without rebuilding.
    """
    await _require_project_access(project_id, session, context)
    from app.services.knowledge_graph_builder import rebuild_project_graph_snapshot

    snapshot = await rebuild_project_graph_snapshot(
        session,
        tenant_id=context.tenant_id,
        project_id=project_id,
        user_id=context.user_id,
    )
    full = snapshot.get("fullGraph") or {"nodes": [], "edges": []}
    return {
        "lastUpdated": snapshot.get("generatedAt", ""),
        "snapshotId": snapshot.get("id"),
        "nodeCount": len(full.get("nodes", [])),
        "edgeCount": len(full.get("edges", [])),
        "pipelineVersion": snapshot.get("pipelineVersion", ""),
    }
