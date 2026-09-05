"""KG-24/KG-25: a minimal node/edge-type schema registry.

A full schema registry (required properties, allowed source types,
permissible relationship directions, cardinality, and evidence
requirements for every node/edge type) is a substantially larger effort
than this module attempts -- the review's own example ("a dashboard
`governs` a tenant is rejected before persistence") only actually applies
to one write path in the current codebase: ``create_family_relationship_edges``
(``app/services/project_graph_service/linking.py``), the sole place a
free-form, LLM-supplied ``target_type``/``relationship_type`` string
reaches ``ai_project_graph_nodes``/``ai_project_graph_edges`` with no
existing type-appropriateness check. Every other node/edge is emitted from
a single, hardcoded call site with an already-fixed, correct type and
direction (verified by code review across every emission site), so this
module targets the one place validation is actually needed rather than
building a general-purpose registry with no second consumer yet.
"""

from __future__ import annotations

from typing import Any

# Node types created exclusively by the structural collector
# (``app/services/knowledge_graph_context/collectors.py``) or another
# trusted, source-anchored pipeline. A free-form target_type string (from
# an LLM-proposed family relationship) must never be allowed to claim one
# of these -- a node named "dashboard" with no real source_id/source_type
# backing it would be indistinguishable from, and could graph_key-collide
# with, the real structural dashboard node for the same project.
#
# "document" is deliberately NOT included here: an existing, tested
# pattern (``tests/test_document_families.py::test_relationship_edges_created``)
# uses ``target_type="document"`` for a family relationship pointing at a
# document that's referenced by name but not (yet) itself a structural
# node with a real ``source_id`` -- a legitimate placeholder, not an
# impersonation of the real structural document type, since it never
# carries a ``source_type``/``source_id`` of its own to collide on.
RESERVED_STRUCTURAL_NODE_TYPES = frozenset({
    "project",
    "data_source",
    "saved_query",
    "dashboard",
    "kpi",
    "reference_document",
})

# Known inverse relationship pairs -- not an exhaustive schema, just the
# pairs that already coexist as unordered members of the same allow-lists
# today (``FAMILY_RELATIONSHIP_TYPES``, ``knowledge_graph/constants.py``'s
# ``_EVIDENCE_EDGE_TYPES``), consulted only for the direction/contradiction
# check below.
INVERSE_OF: dict[str, str] = {
    "governs": "governed_by",
    "governed_by": "governs",
    "supersedes": "superseded_by",
    "superseded_by": "supersedes",
}


def is_reserved_structural_type(node_type: str | None) -> bool:
    """Would ``node_type`` collide with a real structural node type."""
    return (node_type or "").strip().lower() in RESERVED_STRUCTURAL_NODE_TYPES


def inverse_of(relationship_type: str | None) -> str | None:
    """The known logical inverse of ``relationship_type``, if any."""
    return INVERSE_OF.get((relationship_type or "").strip().lower())


def detect_contradictory_direction_edges(
    edges: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """KG-25: pairs of edges asserting the same ``relationship_type`` in
    both directions between the same two nodes (A--rel-->B *and*
    B--rel-->A).

    A same-type relationship that isn't inherently symmetric can't
    correctly hold in both directions at once between the same pair --
    this is a signal of a real modeling error (a duplicate/AI-proposed
    edge accidentally reversed), not normal graph structure, so every
    genuine pair is reported once regardless of which one was "first."
    """
    by_key: dict[tuple[Any, Any, str], dict[str, Any]] = {}
    for e in edges:
        from_id, to_id = e.get("from_node_id"), e.get("to_node_id")
        rel = str(e.get("relationship_type") or "")
        if from_id is None or to_id is None or from_id == to_id:
            continue
        by_key[(from_id, to_id, rel)] = e

    contradictions: list[tuple[dict[str, Any], dict[str, Any]]] = []
    reported: set[frozenset] = set()
    for (from_id, to_id, rel), edge in by_key.items():
        pair_marker = frozenset({(from_id, to_id, rel), (to_id, from_id, rel)})
        if pair_marker in reported:
            continue
        reverse_edge = by_key.get((to_id, from_id, rel))
        if reverse_edge is not None:
            contradictions.append((edge, reverse_edge))
            reported.add(pair_marker)
    return contradictions
