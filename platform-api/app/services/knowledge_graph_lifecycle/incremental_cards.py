"""KG-42: decide which AI insight-card centres an incremental rebuild must
re-enrich, instead of always carrying the active snapshot's cards over
unchanged.

An incremental rebuild reloads the full stored graph (cheap) but previously
skipped AI enrichment entirely to avoid the cost of a full rebuild -- so a
KPI/process/document that actually changed kept showing stale insight cards
until the next full rebuild. This module compares the graph before and after
the incremental patch to find exactly which cached centres are stale, so only
those need a fresh AI call.
"""

from __future__ import annotations

from typing import Any

from app.services.knowledge_graph_builder import _center_eligible_keys, enrich_node


def _touched_node_ids(
    old_nodes: list[dict[str, Any]],
    old_edges: list[dict[str, Any]],
    new_nodes: list[dict[str, Any]],
    new_edges: list[dict[str, Any]],
) -> set[Any]:
    """Node ids that were added, removed, changed, or gained/lost an edge."""
    old_by_id = {n.get("id"): n for n in old_nodes}
    new_by_id = {n.get("id"): n for n in new_nodes}
    touched: set[Any] = set(old_by_id) ^ set(new_by_id)
    for nid in set(old_by_id) & set(new_by_id):
        if old_by_id[nid] != new_by_id[nid]:
            touched.add(nid)

    old_edges_by_id = {e.get("id"): e for e in old_edges}
    new_edges_by_id = {e.get("id"): e for e in new_edges}
    changed_edge_ids = set(old_edges_by_id) ^ set(new_edges_by_id)
    for eid in set(old_edges_by_id) & set(new_edges_by_id):
        if old_edges_by_id[eid] != new_edges_by_id[eid]:
            changed_edge_ids.add(eid)
    for eid in changed_edge_ids:
        edge = old_edges_by_id.get(eid) or new_edges_by_id.get(eid)
        if edge is None:
            continue
        touched.add(edge.get("from_node_id"))
        touched.add(edge.get("to_node_id"))

    touched.discard(None)
    return touched


def affected_center_keys(
    *,
    old_nodes: list[dict[str, Any]],
    old_edges: list[dict[str, Any]],
    new_nodes: list[dict[str, Any]],
    new_edges: list[dict[str, Any]],
    cached_cards_by_center: dict[str, Any],
) -> tuple[list[str], list[str]]:
    """Return ``(refresh_keys, stale_keys)`` for the incremental patch.

    ``refresh_keys``: centres whose cached bundle must be regenerated -- the
    centre node itself changed, a cached card's evidence traced through a
    node that changed, or the centre is newly eligible with no cached bundle.

    ``stale_keys``: cached centres that are no longer centre-eligible at all
    (the underlying node was deleted or deactivated) and should be evicted
    rather than left showing cards for a node that no longer exists.
    """
    touched = _touched_node_ids(old_nodes, old_edges, new_nodes, new_edges)
    current_keys = set(_center_eligible_keys(new_nodes))

    key_to_id: dict[str, Any] = {}
    for n in new_nodes:
        enriched = enrich_node(n)
        key = enriched.get("graphKey")
        if key:
            key_to_id[key] = enriched.get("id")

    refresh: set[str] = set()
    for key in current_keys:
        cached = cached_cards_by_center.get(key)
        if cached is None:
            refresh.add(key)
            continue
        if key_to_id.get(key) in touched:
            refresh.add(key)
            continue
        for card in cached.get("insightCards") or []:
            trace_ids = (card.get("traceToEvidence") or {}).get("nodeIds") or []
            if touched.intersection(trace_ids):
                refresh.add(key)
                break

    stale = [key for key in cached_cards_by_center if key not in current_keys]
    return sorted(refresh), sorted(stale)
