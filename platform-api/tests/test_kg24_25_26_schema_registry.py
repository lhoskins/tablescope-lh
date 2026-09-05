"""KG-24/25/26: a minimal node/edge-type schema registry, direction/
inverse-consistency detection, and graph-key collision visibility.

Confirmed gaps (research pass, no code-verified prior test of these):
1. KG-24: ``create_family_relationship_edges`` (the sole write path where a
   free-form, LLM-supplied ``target_type`` string reaches
   ``ai_project_graph_nodes`` with no type-appropriateness check) could
   create a fake node claiming a reserved structural type (e.g.
   "dashboard", "project") -- indistinguishable from, and possibly
   graph_key-colliding with, the real structural node.
2. KG-25: no mechanism detected a same-type relationship asserted in both
   directions between the same two nodes (a modeling error, not normal
   graph structure).
3. KG-26: ``merge_graph_sources`` silently dropped a losing node on a
   graph_key collision with zero record, even when the two colliding
   nodes were provably different underlying records (different
   source_type/source_id) -- now logged as a warning.

Run from ``platform-api``:
``pytest -q tests/test_kg24_25_26_schema_registry.py``.
"""

from __future__ import annotations

import logging

from app.services.knowledge_graph.loader import merge_graph_sources
from app.services.knowledge_graph.schema_registry import (
    RESERVED_STRUCTURAL_NODE_TYPES,
    detect_contradictory_direction_edges,
    inverse_of,
    is_reserved_structural_type,
)
from app.services.knowledge_graph_lifecycle.structural_integrity import (
    evaluate_structural_integrity,
)


def test_is_reserved_structural_type_matches_every_registered_type():
    for t in RESERVED_STRUCTURAL_NODE_TYPES:
        assert is_reserved_structural_type(t)
    assert not is_reserved_structural_type("process")
    assert not is_reserved_structural_type("risk")
    assert not is_reserved_structural_type(None)


def test_inverse_of_known_pairs_round_trips():
    assert inverse_of("governs") == "governed_by"
    assert inverse_of("governed_by") == "governs"
    assert inverse_of("supersedes") == "superseded_by"
    assert inverse_of("some_unknown_type") is None


def test_detect_contradictory_direction_edges_flags_a_reversed_pair():
    edges = [
        {"from_node_id": 1, "to_node_id": 2, "relationship_type": "governs"},
        {"from_node_id": 2, "to_node_id": 1, "relationship_type": "governs"},
    ]
    contradictions = detect_contradictory_direction_edges(edges)
    assert len(contradictions) == 1


def test_detect_contradictory_direction_edges_ignores_normal_structure():
    edges = [
        {"from_node_id": 1, "to_node_id": 2, "relationship_type": "reads_from"},
        {"from_node_id": 1, "to_node_id": 3, "relationship_type": "reads_from"},
        {"from_node_id": 2, "to_node_id": 1, "relationship_type": "measures"},
    ]
    assert detect_contradictory_direction_edges(edges) == []


def test_evaluate_structural_integrity_warns_on_contradictory_direction():
    nodes = [
        {"id": "hub", "node_type": "project"},
        {"id": "a", "node_type": "document"},
        {"id": "b", "node_type": "document_family"},
    ]
    edges = [
        {"from_node_id": "hub", "to_node_id": "a", "relationship_type": "documents"},
        {"from_node_id": "a", "to_node_id": "b", "relationship_type": "governs"},
        {"from_node_id": "b", "to_node_id": "a", "relationship_type": "governs"},
    ]
    result = evaluate_structural_integrity(nodes, edges)
    assert result["contradictory_direction_count"] == 1
    assert any("both directions" in w for w in result["warnings"])
    # A warning is non-blocking -- it must not affect activation validity.
    assert result["valid"] is True


def test_evaluate_structural_integrity_no_contradiction_when_only_one_direction():
    nodes = [
        {"id": "hub", "node_type": "project"},
        {"id": "a", "node_type": "document"},
        {"id": "b", "node_type": "document_family"},
    ]
    edges = [
        {"from_node_id": "hub", "to_node_id": "a", "relationship_type": "documents"},
        {"from_node_id": "a", "to_node_id": "b", "relationship_type": "governs"},
    ]
    result = evaluate_structural_integrity(nodes, edges)
    assert result["contradictory_direction_count"] == 0


def test_merge_graph_sources_logs_a_collision_between_different_sources(caplog):
    stored_nodes = [
        {"id": 1, "node_type": "data_source", "name": "orders",
         "source_type": "file_source", "source_id": 10,
         "properties": {"graph_key": "datasource:orders"}},
    ]
    extra_nodes = [
        {"id": 2, "node_type": "data_source", "name": "orders",
         "source_type": "database_data_source", "source_id": 99,
         "properties": {"graph_key": "datasource:orders"}},
    ]
    with caplog.at_level(logging.WARNING, logger="app.services.knowledge_graph.loader"):
        merged_nodes, _merged_edges = merge_graph_sources(stored_nodes, [], extra_nodes, [])

    assert len(merged_nodes) == 1
    assert any("graph_key_collision" in r.message for r in caplog.records)


def test_merge_graph_sources_does_not_log_for_the_same_underlying_source(caplog):
    stored_nodes = [
        {"id": 1, "node_type": "document", "name": "Handbook",
         "source_type": "project_asset", "source_id": 5,
         "properties": {"graph_key": "document:5"}},
    ]
    extra_nodes = [
        {"id": 2, "node_type": "document", "name": "Handbook",
         "source_type": "project_asset", "source_id": 5,
         "properties": {"graph_key": "document:5"}},
    ]
    with caplog.at_level(logging.WARNING, logger="app.services.knowledge_graph.loader"):
        merged_nodes, _merged_edges = merge_graph_sources(stored_nodes, [], extra_nodes, [])

    assert len(merged_nodes) == 1
    assert not any("graph_key_collision" in r.message for r in caplog.records)
