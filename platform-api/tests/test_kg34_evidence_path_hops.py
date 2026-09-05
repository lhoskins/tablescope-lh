"""KG-34: build real evidence paths, not only evidence-node lists.

Validated gap: ``traceToEvidence``/``tracePaths`` only ever carried flat
``nodeIds``/``edgeIds`` lists -- a star-shaped, one-hop set with no edge
direction or relationship meaning embedded anywhere in the trace structure
itself (a UI would have to separately look up each edge id in the top-level
``edges`` array and guess how the hops chain together). The AI-enriched
path (``knowledge_graph_ai.py``) was worse: its evidence-id sequence was
built from a plain Python ``set``, with no guaranteed order at all.

Run from ``platform-api``: ``pytest -q tests/test_kg34_evidence_path_hops.py``.
"""

from __future__ import annotations

from app.services import knowledge_graph_ai as kg_ai
from app.services.knowledge_graph_builder import build_graph_payload


def _nodes() -> list[dict]:
    return [
        {"id": 1, "node_type": "project", "name": "Proj", "source_type": None, "source_id": None, "properties": {"project_id": 7}},
        {"id": 2, "node_type": "risk", "name": "CAPA Slippage", "source_type": None, "source_id": None, "properties": {"confidence": 0.95, "summary": "CAPA workflow risk.", "graph_key": "risk:capa_slippage"}},
        {"id": 3, "node_type": "policy", "name": "Quality Manual", "source_type": "asset", "source_id": 30, "properties": {"summary": "Governs CAPA."}},
        {"id": 4, "node_type": "kpi", "name": "On-time Closure", "source_type": None, "source_id": None, "properties": {}},
    ]


def _edges() -> list[dict]:
    def e(eid, a, b, rel, conf):
        return {"id": eid, "from_node_id": a, "to_node_id": b, "relationship_type": rel, "confidence": conf, "evidence": {}}

    return [
        e(1, 1, 2, "contains", 0.99),
        e(2, 3, 2, "governs", 0.95),
        e(3, 2, 4, "measures", 0.9),
    ]


def _payload() -> dict:
    return build_graph_payload(_nodes(), _edges(), center_node="risk:capa_slippage")


def test_structural_card_carries_an_ordered_direction_aware_hop_per_evidence_edge():
    payload = _payload()
    card = next(c for c in payload["insightCards"] if c["nodeKey"] == "risk:capa_slippage")
    hops = card["traceToEvidence"]["hops"]
    assert hops
    for hop in hops:
        assert set(hop) == {"fromNodeId", "toNodeId", "relationshipType"}
    # The policy->risk "governs" edge is real evidence for this center.
    assert any(
        h["fromNodeId"] == 3 and h["toNodeId"] == 2 and h["relationshipType"] == "governs"
        for h in hops
    )


def test_top_level_trace_path_carries_the_same_hops_as_its_card():
    payload = _payload()
    card = next(c for c in payload["insightCards"] if c["nodeKey"] == "risk:capa_slippage")
    trace = next(t for t in payload["tracePaths"] if t["fromNodeKey"] == "risk:capa_slippage")
    assert trace["hops"] == card["traceToEvidence"]["hops"]


def test_ai_mapped_card_evidence_ids_are_ordered_not_a_bare_set():
    payload = _payload()
    center = payload["centerNode"]
    nodes_by_key = {n["graphKey"]: n for n in payload["nodes"]}
    raw = {
        "id": "c1", "category": "risk", "title": "CAPA closures slipping",
        "confidence": 0.9,
        "evidenceKeys": ["policy:3", "kpi:on_time_closure"],
    }
    card = kg_ai._map_card(
        raw, index=0, center=center, nodes_by_key=nodes_by_key,
        nodes=payload["nodes"], edges=payload["edges"],
    )
    assert card is not None
    node_ids = card["traceToEvidence"]["nodeIds"]
    assert isinstance(node_ids, list)
    assert node_ids[0] == center["id"]


def test_ai_mapped_card_carries_direction_aware_hops_from_real_grounding_edges():
    payload = _payload()
    center = payload["centerNode"]
    nodes_by_key = {n["graphKey"]: n for n in payload["nodes"]}
    raw = {
        "id": "c1", "category": "risk", "title": "CAPA closures slipping",
        "confidence": 0.9,
        "evidenceKeys": ["policy:3", "kpi:on_time_closure"],
    }
    card = kg_ai._map_card(
        raw, index=0, center=center, nodes_by_key=nodes_by_key,
        nodes=payload["nodes"], edges=payload["edges"],
    )
    assert card is not None
    hops = card["traceToEvidence"]["hops"]
    assert hops
    for hop in hops:
        assert set(hop) == {"fromNodeId", "toNodeId", "relationshipType"}
