"""Tests for the knowledge graph payload renderer and edge payload shape."""

from __future__ import annotations

import pytest

from app.services.knowledge_graph.renderer import _edge_payload, build_graph_payload


def _node(node_id: int, node_type: str, name: str = "") -> dict:
    return {
        "id": node_id,
        "node_type": node_type,
        "name": name or f"{node_type}-{node_id}",
        "properties": {},
    }


@pytest.fixture
def sample_graph():
    """Three document nodes with explicit, inferred and weak edges between them."""
    nodes = [
        _node(1, "document", "Doc A"),
        _node(2, "document", "Doc B"),
        _node(3, "document", "Doc C"),
    ]
    edges = [
        # Explicit, high-confidence edge.
        {
            "id": 10,
            "from_node_id": 1,
            "to_node_id": 2,
            "relationship_type": "contains",
            "confidence": 0.95,
            "evidence": {"validation_status": "validated"},
        },
        # Inferred edge with confidence above the inferred display floor.
        {
            "id": 11,
            "from_node_id": 1,
            "to_node_id": 3,
            "relationship_type": "linked_by_inferred_join",
            "confidence": 0.80,
            "evidence": {"validation_status": "inferred"},
        },
        # Weak edge that should be filtered below the default floor.
        {
            "id": 12,
            "from_node_id": 2,
            "to_node_id": 3,
            "relationship_type": "mentions",
            "confidence": 0.40,
            "evidence": {},
        },
    ]
    return nodes, edges


def test_build_graph_payload_filters_by_min_confidence_and_includes_inferred(
    sample_graph,
):
    nodes, edges = sample_graph
    # include_inferred=True sets the floor to INFERRED_FLOOR (0.50), so the
    # 0.40 weak edge is dropped but the 0.80 inferred edge is kept.
    payload = build_graph_payload(nodes, edges, include_inferred=True, min_confidence=0.5)

    assert payload["centerNode"] is not None
    assert payload["stats"]["nodeCount"] >= 2
    assert payload["stats"]["edgeCount"] == 2
    edge_ids = {e["id"] for e in payload["edges"]}
    assert 10 in edge_ids
    assert 11 in edge_ids
    assert 12 not in edge_ids


def test_build_graph_payload_hides_inferred_without_include_inferred(
    sample_graph,
):
    nodes, edges = sample_graph
    # With include_inferred=False the floor is min_confidence (0.90), so the
    # 0.80 inferred edge is dropped and only the validated 0.95 edge remains.
    payload = build_graph_payload(nodes, edges, include_inferred=False, min_confidence=0.9)

    assert payload["stats"]["edgeCount"] == 1
    assert payload["edges"][0]["id"] == 10
    assert payload["edges"][0]["connectorStyle"] == "solid"


def test_build_graph_payload_returns_full_contract_keys():
    nodes = [_node(1, "document", "Doc A"), _node(2, "document", "Doc B")]
    edges = [
        {
            "id": 10,
            "from_node_id": 1,
            "to_node_id": 2,
            "relationship_type": "contains",
            "confidence": 0.95,
            "evidence": {},
        }
    ]
    payload = build_graph_payload(nodes, edges, include_inferred=True, min_confidence=0.5)

    assert set(payload.keys()) >= {
        "centerNode",
        "nodes",
        "edges",
        "insightCards",
        "gaps",
        "recommendedActions",
        "tracePaths",
        "stats",
        "lens",
        "minConfidence",
        "includeInferred",
        "generated_at",
        "pipeline_version",
    }
    assert payload["pipeline_version"] != ""
    assert payload["stats"]["nodeCount"] >= 1
    assert payload["stats"]["edgeCount"] >= 1


def test_edge_payload_shape_and_classification():
    edge = {
        "id": 42,
        "from_node_id": 1,
        "to_node_id": 2,
        "relationship_type": "contains",
        "confidence": 0.95,
        "evidence": {"validation_status": "validated", "evidence_summary": "Found in doc A"},
    }
    enriched = {
        1: {"id": 1, "type": "document", "properties": {}},
        2: {"id": 2, "type": "document", "properties": {}},
    }
    result = _edge_payload(edge, enriched)

    assert result["id"] == 42
    assert result["source"] == 1
    assert result["target"] == 2
    assert result["type"] == "contains"
    assert result["confidence"] == 0.95
    assert result["relationshipStrength"] == "explicit"
    assert result["connectorStyle"] == "solid"
    assert result["displayByDefault"] is True
    assert result["validationStatus"] == "validated"
    assert result["evidenceSummary"] == "Found in doc A"
    assert "evidenceBasis" in result
    assert "evidence" in result


def test_build_graph_payload_empty_graph_returns_zero_stats():
    payload = build_graph_payload([], [], include_inferred=True, min_confidence=0.5)
    assert payload["centerNode"] is None
    assert payload["nodes"] == []
    assert payload["edges"] == []
    assert payload["stats"]["nodeCount"] == 0
    assert payload["stats"]["edgeCount"] == 0
