
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .graph_primitives import _as_dict
from .linking import _edge_role

# ── Reads ────────────────────────────────────────────────────────────

async def get_family_members(
    session: AsyncSession,
    tenant_id: int,
    project_id: int,
    family_node_id: int,
) -> dict[str, list[dict[str, Any]]]:
    """Return active family members grouped by kind.

    Documents come from belongs_to_family edges; datasources/kpis/entities/tags
    are aggregated from the active edges of those member documents.
    """
    members: dict[str, list[dict[str, Any]]] = {
        "documents": [], "datasources": [], "queries": [],
        "dashboards": [], "kpis": [], "entities": [],
    }

    doc_rows = await session.execute(
        text(
            """
            SELECT n.id, n.name, n.source_id, n.properties, e.confidence, e.evidence
            FROM ai_project_graph_edges e
            JOIN ai_project_graph_nodes n ON n.id = e.from_node_id
            WHERE e.tenant_id=:tid AND e.project_id=:pid
              AND e.to_node_id=:famid AND e.relationship_type='belongs_to_family'
              AND e.is_active=true AND n.is_active=true
            ORDER BY e.confidence DESC NULLS LAST, n.id
            """
        ),
        {"tid": tenant_id, "pid": project_id, "famid": family_node_id},
    )
    doc_ids: list[int] = []
    for nid, name, sid, props, conf, ev in doc_rows.fetchall():
        doc_ids.append(nid)
        p = _as_dict(props)
        members["documents"].append({
            "node_id": nid, "name": name, "source_id": sid,
            "summary": p.get("summary", ""), "role": _edge_role(ev),
            "confidence": float(conf or 0),
        })

    if not doc_ids:
        return members

    # Aggregate the documents' connected nodes into typed member buckets.
    id_placeholders = ", ".join(f":d{i}" for i in range(len(doc_ids)))
    rel_params: dict[str, Any] = {"tid": tenant_id, "pid": project_id}
    for i, did in enumerate(doc_ids):
        rel_params[f"d{i}"] = did
    rel_rows = await session.execute(
        text(
            f"""
            SELECT DISTINCT n.id, n.node_type, n.name, n.source_id
            FROM ai_project_graph_edges e
            JOIN ai_project_graph_nodes n ON n.id = e.to_node_id
            WHERE e.tenant_id=:tid AND e.project_id=:pid
              AND e.from_node_id IN ({id_placeholders})
              AND e.relationship_type<>'belongs_to_family'
              AND e.is_active=true AND n.is_active=true
            """
        ),
        rel_params,
    )
    seen: set[tuple[str, str]] = set()
    for nid, ntype, name, sid in rel_rows.fetchall():
        bucket = {
            "datasource": "datasources", "kpi": "kpis",
        }.get(ntype)
        if bucket is None:
            # Treat tags + named entities as entity-like members.
            if ntype in ("document_family", "tag"):
                continue
            bucket = "entities"
        key = (bucket, name)
        if key in seen:
            continue
        seen.add(key)
        members[bucket].append({"node_id": nid, "name": name, "source_id": sid, "type": ntype})

    return members


async def get_family_node(
    session: AsyncSession,
    tenant_id: int,
    project_id: int,
    family_node_id: int,
) -> dict[str, Any] | None:
    result = await session.execute(
        text(
            """
            SELECT id, name, properties FROM ai_project_graph_nodes
            WHERE id=:id AND tenant_id=:tid AND project_id=:pid
              AND node_type='document_family'
            """
        ),
        {"id": family_node_id, "tid": tenant_id, "pid": project_id},
    )
    row = result.fetchone()
    if not row:
        return None
    nid, name, props = row
    return {"id": nid, "name": name, "properties": _as_dict(props)}
