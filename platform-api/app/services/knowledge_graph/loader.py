"""Knowledge graph node/edge loading and neighborhood selection."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .classifier import _edge_confidence
from .constants import (
    _LENS_BY_TYPE,
    _PRIORITY_NEIGHBOR_TYPES,
    MAX_NEIGHBORHOOD_NODES,
    _as_dict,
    _display_group_for,
    _layer_for,
    _severity_for,
    graph_key_for,
)

logger = logging.getLogger(__name__)

def enrich_node(node: dict[str, Any]) -> dict[str, Any]:
    """Augment a raw node row with graph metadata used by the UI."""
    props = _as_dict(node.get("properties"))
    ntype = str(node.get("node_type") or node.get("type") or "node")
    name = str(node.get("name") or node.get("label") or "")
    key = graph_key_for(node)

    confidence = props.get("confidence")
    try:
        confidence = round(float(confidence), 4) if confidence is not None else None
    except (TypeError, ValueError):
        confidence = None

    return {
        "id": node.get("id"),
        "type": ntype,
        "label": name,
        "source_type": node.get("source_type"),
        "source_id": node.get("source_id"),
        "properties": props,
        "graphKey": key,
        "layer": _layer_for(ntype),
        "displayGroup": _display_group_for(ntype),
        "severity": _severity_for(ntype, props),
        "summary": str(props.get("summary") or props.get("description") or ""),
        "businessValue": str(props.get("business_value") or ""),
        "businessQuestion": str(props.get("business_question") or ""),
        "confidence": confidence,
        "isCenterEligible": True,
        "clickAction": "center_graph",
        "recommendedLens": _LENS_BY_TYPE.get(ntype, "insight-first"),
    }


def _is_canvas_hidden(node: dict[str, Any]) -> bool:
    """The project hub stays the security/data boundary but is never drawn.

    Accepts both raw rows (``node_type``/``properties`` may be JSON) and enriched
    nodes (``type``/``properties`` dict).
    """
    ntype = node.get("type") or node.get("node_type")
    props = _as_dict(node.get("properties"))
    return ntype == "project" or props.get("hidden_on_canvas") is True


def _pick_center(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    center_node: str | None,
) -> dict[str, Any] | None:
    """Resolve the center node from a graph key / id, with sensible defaults.

    The project node is never chosen as the center — the graph centers on the
    selected (or highest-signal) process / document family / document / entity.
    """
    if not nodes:
        return None
    by_key = {n["graphKey"]: n for n in nodes}
    by_id = {str(n["id"]): n for n in nodes}

    if center_node:
        if center_node in by_key:
            return by_key[center_node]
        if center_node in by_id:
            return by_id[center_node]

    pool = [n for n in nodes if not _is_canvas_hidden(n)] or nodes

    # Prefer a process (the mockup centers on a process), then a document
    # family, then a document, then the highest-degree remaining node.
    processes = [n for n in pool if n["type"] == "process"]
    if processes:
        return _highest_degree(processes, edges)
    families = [n for n in pool if n["type"] == "document_family"]
    if families:
        return _highest_degree(families, edges)
    documents = [
        n for n in pool
        if n["type"] in ("document", "reference_document", "policy", "procedure", "standard")
    ]
    if documents:
        return _highest_degree(documents, edges)
    return _highest_degree(pool, edges)


def _highest_degree(
    candidates: list[dict[str, Any]], edges: list[dict[str, Any]],
) -> dict[str, Any]:
    degree: dict[Any, int] = {}
    for e in edges:
        degree[e["from_node_id"]] = degree.get(e["from_node_id"], 0) + 1
        degree[e["to_node_id"]] = degree.get(e["to_node_id"], 0) + 1
    return max(candidates, key=lambda n: degree.get(n["id"], 0))


def _neighborhood(
    center: dict[str, Any],
    nodes_by_id: dict[Any, dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    max_nodes: int = MAX_NEIGHBORHOOD_NODES,
) -> tuple[set[Any], list[dict[str, Any]]]:
    """BFS up to 2 hops from the center, keeping the strongest edges first.

    Returns the set of kept node ids and the edges fully inside that set.
    """
    adjacency: dict[Any, list[tuple[Any, dict[str, Any]]]] = {}
    for e in edges:
        adjacency.setdefault(e["from_node_id"], []).append((e["to_node_id"], e))
        adjacency.setdefault(e["to_node_id"], []).append((e["from_node_id"], e))

    def _priority(pair: tuple[Any, dict[str, Any]]) -> tuple[int, float]:
        other = nodes_by_id.get(pair[0]) or {}
        boost = 1 if other.get("type") in _PRIORITY_NEIGHBOR_TYPES else 0
        return (boost, _edge_confidence(pair[1]))

    kept: set[Any] = {center["id"]}
    frontier = [center["id"]]
    for _hop in range(2):
        next_frontier: list[Any] = []
        for nid in frontier:
            neighbors = sorted(
                adjacency.get(nid, []),
                key=_priority,
                reverse=True,
            )
            for other_id, _edge in neighbors:
                if other_id in kept:
                    continue
                if other_id not in nodes_by_id:
                    continue
                if len(kept) >= max_nodes:
                    break
                kept.add(other_id)
                next_frontier.append(other_id)
            if len(kept) >= max_nodes:
                break
        frontier = next_frontier
        if not frontier or len(kept) >= max_nodes:
            break

    # Guarantee high-value nodes are never crowded out of the capped
    # neighborhood: KPIs/metrics, findings and actions must always render even
    # when the bulk reference library fills the cap first. A KPI may sit two hops
    # out (via its measuring query/dashboard), so pull it in whenever it connects
    # to the kept set within two hops — and keep that connector too so the
    # measurement edge renders. The priority set is small, so this stays bounded.
    priority_ids = [
        nid for nid, n in nodes_by_id.items()
        if n.get("type") in _PRIORITY_NEIGHBOR_TYPES and nid not in kept
    ]
    for pid in priority_ids:
        for other_id, _edge in adjacency.get(pid, []):
            if other_id in kept:
                kept.add(pid)
                break
            if any(o2 in kept for o2, _e2 in adjacency.get(other_id, [])):
                kept.add(pid)
                kept.add(other_id)
                break

    kept_edges = [
        e for e in edges if e["from_node_id"] in kept and e["to_node_id"] in kept
    ]
    return kept, kept_edges


# ── Insight cards / gaps / recommendations ───────────────────────────

def merge_graph_sources(
    stored_nodes: list[dict[str, Any]],
    stored_edges: list[dict[str, Any]],
    extra_nodes: list[dict[str, Any]],
    extra_edges: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Merge stored (AI) graph rows with structural rows, deduped by graph key.

    Stored nodes win on collision (they carry AI summaries / properties); the
    structural twin's id is remapped onto the stored node so its edges survive.
    Edges are deduped by (from, to, relationship_type), keeping the strongest.
    """
    canonical_by_key: dict[str, dict[str, Any]] = {}
    id_remap: dict[Any, Any] = {}
    merged_nodes: list[dict[str, Any]] = []

    for n in [*stored_nodes, *extra_nodes]:
        key = graph_key_for(n)
        existing = canonical_by_key.get(key)
        if existing is None:
            canonical_by_key[key] = n
            merged_nodes.append(n)
            id_remap[n["id"]] = n["id"]
        else:
            id_remap[n["id"]] = existing["id"]

    valid_ids = {n["id"] for n in merged_nodes}
    seen: dict[tuple[Any, Any, str], int] = {}
    merged_edges: list[dict[str, Any]] = []
    for e in [*stored_edges, *extra_edges]:
        f = id_remap.get(e["from_node_id"], e["from_node_id"])
        t = id_remap.get(e["to_node_id"], e["to_node_id"])
        if f == t or f not in valid_ids or t not in valid_ids:
            continue
        remapped = {**e, "from_node_id": f, "to_node_id": t}
        ekey = (f, t, str(e.get("relationship_type") or ""))
        prev = seen.get(ekey)
        if prev is not None:
            if _edge_confidence(remapped) > _edge_confidence(merged_edges[prev]):
                merged_edges[prev] = remapped
            continue
        seen[ekey] = len(merged_edges)
        merged_edges.append(remapped)
    return merged_nodes, merged_edges


# ── Snapshot persistence (cache) ─────────────────────────────────────

async def _load_stored_graph(
    session: AsyncSession, *, tenant_id: int, project_id: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Load the stored AI graph rows merged with the structural Evidence graph."""
    node_rows = await session.execute(
        text(
            """
            SELECT id, node_type, name, source_type, source_id, properties
            FROM ai_project_graph_nodes
            WHERE tenant_id=:tid AND project_id=:pid AND is_active=true
            ORDER BY id
            """
        ),
        {"tid": tenant_id, "pid": project_id},
    )
    raw_nodes = [
        {
            "id": r[0], "node_type": r[1], "name": r[2],
            "source_type": r[3], "source_id": r[4], "properties": r[5],
        }
        for r in node_rows.fetchall()
    ]

    edge_rows = await session.execute(
        text(
            """
            SELECT id, from_node_id, to_node_id, relationship_type, confidence, evidence
            FROM ai_project_graph_edges
            WHERE tenant_id=:tid AND project_id=:pid AND is_active=true
            """
        ),
        {"tid": tenant_id, "pid": project_id},
    )
    raw_edges = [
        {
            "id": r[0], "from_node_id": r[1], "to_node_id": r[2],
            "relationship_type": r[3], "confidence": r[4], "evidence": r[5],
        }
        for r in edge_rows.fetchall()
    ]

    # Evidence Collector: fold the project's real assets (documents, reference
    # library, data sources, queries, dashboards) into the graph so every node's
    # related sources are present with directional, labelled edges.
    from app.services.knowledge_graph_context import collect_structural_graph

    extra_nodes, extra_edges, _hub_key = await collect_structural_graph(
        session, tenant_id=tenant_id, project_id=project_id,
    )
    return merge_graph_sources(raw_nodes, raw_edges, extra_nodes, extra_edges)


