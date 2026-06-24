"""Evidence Collector for the Insight-First Knowledge Graph.

Builds *structural* graph nodes and edges from the project's real assets — the
documents, the authoritative reference library (project + company + industry),
the linked data sources / tables, the saved queries, and the dashboards — and
connects them to the project hub so the node-centric graph always shows the data
sources related to a node (with directional, labelled edges).

These synthetic nodes/edges are merged with the AI-generated
``ai_project_graph_nodes`` / ``ai_project_graph_edges`` (processes, KPIs, risks,
relationships, gaps) before the node-centric payload is built. Dedup is by the
stable ``graph_key`` so a stored node and its structural twin collapse into one.

Nothing here is fabricated: every node maps to a row the user actually owns, and
every edge is a factual containment/lineage relationship (confidence 1.0).
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dashboard import Dashboard
from app.models.database_data_source import DatabaseDataSource
from app.models.file_source_meta import FileSourceMeta
from app.models.project import Project
from app.models.project_asset import ProjectAsset
from app.models.reference_library import (
    TIER_COMPANY,
    TIER_INDUSTRY,
    TIER_PROJECT,
    ReferenceDocument,
)
from app.models.saved_query import SavedQuery

logger = logging.getLogger(__name__)

# Caps keep the structural graph readable for very large projects.
_MAX_PER_KIND = 40

# Relationship labels for the project-hub → asset edges (shown on the canvas).
_REL_DOCUMENT = "documents"
_REL_DATA_SOURCE = "data_source"
_REL_QUERY = "query"
_REL_DASHBOARD = "dashboard"
_REL_QUERY_READS = "reads_from"
_REF_REL_BY_TIER = {
    TIER_PROJECT: "project_reference",
    TIER_COMPANY: "company_reference",
    TIER_INDUSTRY: "industry_standard",
}


def _norm(value: str | None) -> str:
    return "".join(
        ch if ch.isalnum() else "_" for ch in (value or "").lower()
    ).strip("_")


def _node(
    node_id: str,
    node_type: str,
    name: str,
    *,
    source_type: str | None,
    source_id: int | None,
    properties: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": node_id,
        "node_type": node_type,
        "name": name,
        "source_type": source_type,
        "source_id": source_id,
        "properties": properties,
    }


def _edge(
    edge_id: str,
    from_id: Any,
    to_id: Any,
    relationship_type: str,
    summary: str,
    *,
    confidence: float = 1.0,
) -> dict[str, Any]:
    return {
        "id": edge_id,
        "from_node_id": from_id,
        "to_node_id": to_id,
        "relationship_type": relationship_type,
        "confidence": confidence,
        "evidence": {"evidence_summary": summary, "structural": True},
    }


async def collect_structural_graph(
    session: AsyncSession,
    *,
    tenant_id: int,
    project_id: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    """Return ``(nodes, edges, project_hub_key)`` for the project's real assets.

    The project hub node (graph_key ``project:{id}``) is always returned so the
    structural sources radiate from it with directional edges.
    """
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != tenant_id:
        return [], [], ""

    hub_id = f"s:project:{project_id}"
    hub_key = f"project:{project_id}"
    nodes: list[dict[str, Any]] = [
        _node(
            hub_id,
            "project",
            project.name or f"Project {project_id}",
            source_type="project",
            source_id=project_id,
            properties={
                "project_id": project_id,
                "graph_key": hub_key,
                "summary": (project.description or "")[:400],
                # The project stays the security/data boundary but is never
                # drawn on the canvas (Knowledge Graph centers on a real node).
                "hidden_on_canvas": True,
                "structural_hub": True,
            },
        )
    ]
    edges: list[dict[str, Any]] = []

    # Map of normalized data-source identifiers → synthetic node id, so saved
    # queries can be linked to the tables they actually read.
    ds_by_name: dict[str, str] = {}

    # ── Linked data sources (uploaded files) ─────────────────────────
    file_sources = (
        await session.scalars(
            select(FileSourceMeta)
            .where(
                FileSourceMeta.project_id == project_id,
                FileSourceMeta.archived.is_(False),
            )
            .order_by(FileSourceMeta.id)
            .limit(_MAX_PER_KIND)
        )
    ).all()
    for fs in file_sources:
        nid = f"s:datasource:file:{fs.id}"
        label = fs.view_name or fs.file_name or f"table {fs.id}"
        nodes.append(
            _node(
                nid,
                "data_source",
                label,
                source_type="file_source",
                source_id=fs.id,
                properties={
                    "graph_key": f"datasource:{_norm(label)}",
                    "summary": f"Uploaded data source ({fs.source_format or 'file'}).",
                    "kind": "file",
                },
            )
        )
        edges.append(
            _edge(
                f"se:ds:file:{fs.id}", hub_id, nid, _REL_DATA_SOURCE,
                f"{label} is a data source in this project.",
            )
        )
        for key in {_norm(fs.view_name), _norm(fs.file_name)}:
            if key:
                ds_by_name[key] = nid

    # ── Linked data sources (database tables) ────────────────────────
    db_sources = (
        await session.scalars(
            select(DatabaseDataSource)
            .where(
                DatabaseDataSource.project_id == project_id,
                DatabaseDataSource.archived.is_(False),
            )
            .order_by(DatabaseDataSource.id)
            .limit(_MAX_PER_KIND)
        )
    ).all()
    for ds in db_sources:
        nid = f"s:datasource:db:{ds.id}"
        label = ds.display_name or ds.table_name or f"table {ds.id}"
        nodes.append(
            _node(
                nid,
                "data_source",
                label,
                source_type="database_data_source",
                source_id=ds.id,
                properties={
                    "graph_key": f"datasource:{_norm(label)}",
                    "summary": f"{ds.db_type} table {ds.table_name}.",
                    "kind": "database",
                },
            )
        )
        edges.append(
            _edge(
                f"se:ds:db:{ds.id}", hub_id, nid, _REL_DATA_SOURCE,
                f"{label} is a data source in this project.",
            )
        )
        for key in {_norm(ds.display_name), _norm(ds.table_name), _norm(ds.teiid_view_name)}:
            if key:
                ds_by_name[key] = nid

    # ── Saved queries (and their table lineage) ──────────────────────
    queries = (
        await session.scalars(
            select(SavedQuery)
            .where(SavedQuery.project_id == project_id)
            .order_by(SavedQuery.id)
            .limit(_MAX_PER_KIND)
        )
    ).all()
    for q in queries:
        nid = f"s:query:{q.id}"
        nodes.append(
            _node(
                nid,
                "saved_query",
                q.name or f"query {q.id}",
                source_type="saved_query",
                source_id=q.id,
                properties={
                    "graph_key": f"query:{q.id}",
                    "summary": (q.description or "")[:300],
                },
            )
        )
        edges.append(
            _edge(
                f"se:q:{q.id}", hub_id, nid, _REL_QUERY,
                f"{q.name} is a saved query in this project.",
            )
        )
        for raw in (q.left_datasource, q.right_datasource):
            key = _norm(raw)
            target = ds_by_name.get(key)
            if target:
                edges.append(
                    _edge(
                        f"se:qds:{q.id}:{target}", nid, target, _REL_QUERY_READS,
                        f"{q.name} reads from this data source.",
                    )
                )

    # ── Dashboards ───────────────────────────────────────────────────
    dashboards = (
        await session.scalars(
            select(Dashboard)
            .where(Dashboard.project_id == project_id)
            .order_by(Dashboard.id)
            .limit(_MAX_PER_KIND)
        )
    ).all()
    for d in dashboards:
        nid = f"s:dashboard:{d.id}"
        nodes.append(
            _node(
                nid,
                "dashboard",
                d.name or f"dashboard {d.id}",
                source_type="dashboard",
                source_id=d.id,
                properties={
                    "graph_key": f"dashboard:{d.id}",
                    "summary": (d.description or "")[:300],
                },
            )
        )
        edges.append(
            _edge(
                f"se:dash:{d.id}", hub_id, nid, _REL_DASHBOARD,
                f"{d.name} is a dashboard in this project.",
            )
        )

    # ── Project documents (assets) ───────────────────────────────────
    assets = (
        await session.scalars(
            select(ProjectAsset)
            .where(ProjectAsset.project_id == project_id)
            .order_by(ProjectAsset.id)
            .limit(_MAX_PER_KIND)
        )
    ).all()
    for a in assets:
        nid = f"s:asset:{a.id}"
        nodes.append(
            _node(
                nid,
                "document",
                a.title or a.filename or f"document {a.id}",
                source_type="project_asset",
                source_id=a.id,
                properties={
                    "summary": (a.ai_summary or a.description or "")[:300],
                },
            )
        )
        edges.append(
            _edge(
                f"se:doc:{a.id}", hub_id, nid, _REL_DOCUMENT,
                f"{a.title} is a document in this project.",
            )
        )

    # ── Authoritative reference library (project + company + industry) ─
    ref_docs = (
        await session.scalars(
            select(ReferenceDocument)
            .where(
                ReferenceDocument.status == "active",
                or_(
                    ReferenceDocument.tier == TIER_INDUSTRY,
                    and_(
                        ReferenceDocument.tier == TIER_COMPANY,
                        ReferenceDocument.tenant_id == tenant_id,
                    ),
                    and_(
                        ReferenceDocument.tier == TIER_PROJECT,
                        ReferenceDocument.project_id == project_id,
                    ),
                ),
            )
            .order_by(ReferenceDocument.updated_at.desc())
            .limit(_MAX_PER_KIND)
        )
    ).all()
    for r in ref_docs:
        nid = f"s:reference:{r.id}"
        rel = _REF_REL_BY_TIER.get(r.tier, "reference")
        nodes.append(
            _node(
                nid,
                "reference_document",
                r.title or f"reference {r.id}",
                source_type="reference_document",
                source_id=r.id,
                properties={
                    "graph_key": f"reference:{r.id}",
                    "summary": (r.ai_summary or "")[:300],
                    "tier": r.tier,
                    "issuing_body": r.issuing_body or "",
                },
            )
        )
        edges.append(
            _edge(
                f"se:ref:{r.id}", hub_id, nid, rel,
                f"{r.title} is an authoritative reference for this project.",
            )
        )

    return nodes, edges, hub_key
