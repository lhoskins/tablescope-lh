"""Shared structural-integrity checks for a Knowledge Graph payload (KG-21,
KG-22, KG-23, KG-47).

Used both to *gate activation* (``rebuild_execution.py`` calls this on a
freshly-built candidate before it can replace the last healthy version) and
to *report health* on an already-active version (``knowledge_graph_health.py``)
-- a single implementation so the two can never silently diverge on what
"structurally sound" means, and so activation is at least as strict as the
health check a candidate will immediately face afterward.

Previously: the disconnected-component count was read from a model field
that was never actually computed (it was always its default, 0) rather than
derived from the candidate's own nodes/edges (KG-22); missing project hubs,
dangling edge references, and a high orphan ratio were warnings, never
blocking (KG-21, KG-23) -- a structurally broken candidate could still
replace the last healthy version.
"""

from __future__ import annotations

from typing import Any

from app.services.knowledge_graph.schema_registry import detect_contradictory_direction_edges

# A candidate whose orphan ratio (nodes with no edge at all) exceeds this
# fraction is rejected outright rather than merely warned about. No
# per-project-type/coverage-based threshold tiers exist in this codebase yet
# (that would need a project-type taxonomy this system doesn't have) -- this
# is a single, deliberately conservative default until one is introduced.
_BLOCKING_ORPHAN_RATIO = 0.5

# Below this many nodes, an orphan ratio is reported but never blocking --
# a brand-new project with only a handful of sources (even a hub-only
# graph) trivially has a "high" orphan ratio without being structurally
# broken; there simply isn't enough source coverage yet to judge. This is
# the "source coverage" half of "blocking thresholds by project type and
# source coverage" -- the project-type half needs a taxonomy this codebase
# doesn't have yet.
_MIN_NODES_FOR_ORPHAN_GATE = 4

# Disconnected-component counts above this are reported but not (yet) made
# blocking on their own -- a graph can legitimately have several genuinely
# separate clusters (e.g. distinct reference-library tiers) without being
# broken; dangling edges and missing hubs are the actual integrity signal.
_WARN_DISCONNECTED_COMPONENTS = 5


def _connected_components(
    node_ids: set[Any], edges: list[dict[str, Any]],
) -> tuple[int, set[Any]]:
    """Union-find over the candidate's own nodes/edges. Returns
    (disconnected_multi_node_component_count, isolated_node_ids).

    A fully isolated node (zero edges) is an orphan, not a "disconnected
    component" -- it's already tracked separately via orphan_ratio/orphan_count.
    "Disconnected components" instead counts genuinely separate multi-node
    clusters beyond the one main graph rooted at the project hub (e.g. a
    reference document connected only to another reference document, with no
    path back to the project) -- the actionable, non-noisy signal the review
    asks for, rather than one "component" per stray orphan leaf.
    """
    parent: dict[Any, Any] = {nid: nid for nid in node_ids}

    def find(x: Any) -> Any:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: Any, b: Any) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    connected_ids: set[Any] = set()
    for e in edges:
        a, b = e.get("from_node_id"), e.get("to_node_id")
        if a in parent and b in parent:
            union(a, b)
            connected_ids.add(a)
            connected_ids.add(b)

    isolated = node_ids - connected_ids
    non_isolated_roots = {find(nid) for nid in connected_ids}
    disconnected_components = max(0, len(non_isolated_roots) - 1)
    return disconnected_components, isolated


def evaluate_structural_integrity(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return ``{valid, errors, warnings, ...}`` for a candidate graph
    payload's own nodes/edges. ``errors`` non-empty means the candidate must
    not be activated; ``warnings`` are reported but non-blocking.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not nodes:
        errors.append("Graph contains no nodes")
        return {
            "valid": False, "errors": errors, "warnings": warnings,
            "node_count": 0, "edge_count": len(edges),
            "project_node_count": 0, "dangling_edge_refs": 0,
            "orphan_ratio": 0.0, "orphan_count": 0,
            "disconnected_components": 0, "isolated_node_count": 0,
            "contradictory_direction_count": 0,
        }

    node_ids = {n.get("id") for n in nodes if n.get("id") is not None}

    project_nodes = [n for n in nodes if n.get("node_type") == "project"]
    if not project_nodes:
        errors.append("Missing required project hub node")
    elif len(project_nodes) > 1:
        warnings.append(f"Multiple project hub nodes found ({len(project_nodes)})")

    # KG-23: a dangling edge (references a node not in this candidate) is a
    # blocking integrity error, not a warning -- every active edge must
    # resolve to two real nodes in the same candidate.
    dangling_edges = 0
    for e in edges:
        from_id, to_id = e.get("from_node_id"), e.get("to_node_id")
        if from_id not in node_ids:
            dangling_edges += 1
        if to_id not in node_ids:
            dangling_edges += 1
    if dangling_edges:
        errors.append(f"{dangling_edges} edge references point to missing nodes")

    # KG-22: actually computed from this candidate's own nodes/edges, not a
    # stale stored value.
    component_count, isolated_ids = _connected_components(node_ids, edges)
    orphan_ids = isolated_ids - {"project"}
    orphan_ratio = (len(orphan_ids) / len(nodes)) if nodes else 0.0

    # KG-21: a materially under-connected candidate is rejected outright --
    # but only once there's enough source coverage for that ratio to mean
    # anything (see _MIN_NODES_FOR_ORPHAN_GATE).
    if orphan_ratio > _BLOCKING_ORPHAN_RATIO and len(nodes) >= _MIN_NODES_FOR_ORPHAN_GATE:
        errors.append(f"High orphan ratio: {orphan_ratio:.2%} (blocking threshold {_BLOCKING_ORPHAN_RATIO:.0%})")
    elif orphan_ratio > 0:
        warnings.append(f"Orphan ratio: {orphan_ratio:.2%}")

    if component_count > _WARN_DISCONNECTED_COMPONENTS:
        warnings.append(f"Many disconnected components: {component_count}")

    # KG-25: a same-type relationship asserted in both directions between
    # the same two nodes (A--rel-->B and B--rel-->A) is a modeling error,
    # not normal graph structure -- reported, not blocking, since it can't
    # (yet) be resolved automatically to which direction is correct.
    contradictions = detect_contradictory_direction_edges(edges)
    if contradictions:
        warnings.append(
            f"{len(contradictions)} relationship(s) asserted in both directions "
            "between the same two nodes"
        )

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "project_node_count": len(project_nodes),
        "dangling_edge_refs": dangling_edges,
        "orphan_ratio": orphan_ratio,
        "orphan_count": len(orphan_ids),
        "disconnected_components": component_count,
        "isolated_node_count": len(isolated_ids),
        "contradictory_direction_count": len(contradictions),
    }
