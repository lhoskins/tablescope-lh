"""KG-35: detect contradictory evidence, not just provenance mismatches.

Validated gap: ``merge_graph_sources`` already logs (KG-26) when two nodes
collide on the same graph key but come from different sources -- but that log
line is the only trace of it anywhere, and it fires identically whether the
two sources agree or actually assert different facts. A collision where the
colliding nodes' own properties disagree (e.g. two sources reporting a
different KPI target) is contradictory evidence about the same real-world
entity, and should be visible to any caller that reads the surviving node's
properties, not buried in a log a caller can't see.

Run from ``platform-api``: ``pytest -q tests/test_kg35_contradictory_evidence.py``.
"""

from __future__ import annotations

from app.services.knowledge_graph.loader import merge_graph_sources


def _node(node_id, *, source_type, source_id, properties):
    return {
        "id": node_id,
        "node_type": "kpi",
        "name": "On-time Closure",
        "source_type": source_type,
        "source_id": source_id,
        "properties": properties,
    }


def test_colliding_nodes_with_different_property_values_record_a_conflict():
    stored = [
        _node(1, source_type="saved_query", source_id=10, properties={
            "graph_key": "kpi:on_time_closure", "target": 95, "unit": "percent",
        }),
    ]
    extra = [
        _node(2, source_type="reference_document", source_id=20, properties={
            "graph_key": "kpi:on_time_closure", "target": 80, "unit": "percent",
        }),
    ]
    merged_nodes, _ = merge_graph_sources(stored, [], extra, [])
    assert len(merged_nodes) == 1
    conflicts = merged_nodes[0]["properties"].get("evidence_conflicts")
    assert conflicts == [{
        "key": "target",
        "keptValue": 95,
        "conflictingValue": 80,
        "conflictingSourceType": "reference_document",
        "conflictingSourceId": 20,
    }]


def test_colliding_nodes_with_agreeing_properties_record_no_conflict():
    stored = [
        _node(1, source_type="saved_query", source_id=10, properties={
            "graph_key": "kpi:on_time_closure", "target": 95, "unit": "percent",
        }),
    ]
    extra = [
        _node(2, source_type="reference_document", source_id=20, properties={
            "graph_key": "kpi:on_time_closure", "target": 95, "unit": "percent",
        }),
    ]
    merged_nodes, _ = merge_graph_sources(stored, [], extra, [])
    assert len(merged_nodes) == 1
    assert not merged_nodes[0]["properties"].get("evidence_conflicts")


def test_same_source_collision_is_never_treated_as_a_conflict():
    stored = [
        _node(1, source_type="saved_query", source_id=10, properties={
            "graph_key": "kpi:on_time_closure", "target": 95,
        }),
    ]
    extra = [
        _node(2, source_type="saved_query", source_id=10, properties={
            "graph_key": "kpi:on_time_closure", "target": 80,
        }),
    ]
    merged_nodes, _ = merge_graph_sources(stored, [], extra, [])
    assert len(merged_nodes) == 1
    assert not merged_nodes[0]["properties"].get("evidence_conflicts")


def test_ignored_keys_never_produce_a_conflict():
    stored = [
        _node(1, source_type="saved_query", source_id=10, properties={
            "graph_key": "kpi:on_time_closure", "confidence": 0.9,
            "summary": "Measured by Query A.", "description": "A KPI.",
        }),
    ]
    extra = [
        _node(2, source_type="reference_document", source_id=20, properties={
            "graph_key": "kpi:on_time_closure", "confidence": 0.5,
            "summary": "Recommended by Policy B.", "description": "Another KPI.",
        }),
    ]
    merged_nodes, _ = merge_graph_sources(stored, [], extra, [])
    assert len(merged_nodes) == 1
    assert not merged_nodes[0]["properties"].get("evidence_conflicts")
