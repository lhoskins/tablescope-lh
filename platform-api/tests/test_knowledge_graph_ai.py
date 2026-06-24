"""Tests for the Knowledge Graph AI enrichment pipeline.

The pipeline hands the deterministic node-centric neighborhood to the AI server
and maps the returned cards back onto the platform card shape, grounded in real
graph nodes. These tests use the deterministic builder to produce a realistic
payload, then exercise the request builder, the card mapper, and the end-to-end
enrichment with a stubbed AI client.
"""

from __future__ import annotations

import pytest

from app.services import knowledge_graph_ai as kg_ai
from app.services.knowledge_graph_builder import build_graph_payload


def _nodes() -> list[dict]:
    return [
        {"id": 1, "node_type": "project", "name": "Proj", "source_type": None, "source_id": None, "properties": {"project_id": 7}},
        {"id": 2, "node_type": "process", "name": "Corrective Action Process", "source_type": None, "source_id": None, "properties": {"confidence": 0.95, "summary": "CAPA workflow."}},
        {"id": 3, "node_type": "policy", "name": "Quality Manual", "source_type": "asset", "source_id": 30, "properties": {"summary": "Governs CAPA."}},
        {"id": 4, "node_type": "kpi", "name": "On-time Closure", "source_type": None, "source_id": None, "properties": {}},
        {"id": 5, "node_type": "data_source", "name": "capa_table", "source_type": "datasource", "source_id": 50, "properties": {}},
        {"id": 6, "node_type": "saved_query", "name": "Open CAPAs", "source_type": "query", "source_id": 60, "properties": {}},
        {"id": 7, "node_type": "dashboard", "name": "CAPA Dashboard", "source_type": "dashboard", "source_id": 70, "properties": {}},
    ]


def _edges() -> list[dict]:
    def e(eid, a, b, rel, conf):
        return {"id": eid, "from_node_id": a, "to_node_id": b, "relationship_type": rel, "confidence": conf, "evidence": {}}

    return [
        e(1, 1, 2, "contains", 0.99),
        e(2, 3, 2, "governs", 0.95),       # policy -> process (direction "in")
        e(3, 2, 4, "measures", 0.9),       # process -> kpi (direction "out")
        e(4, 2, 5, "uses", 0.85),
        e(5, 2, 6, "derived_from", 0.82),
        e(6, 2, 7, "visualizes", 0.8),
    ]


def _payload() -> dict:
    return build_graph_payload(_nodes(), _edges(), center_node="process:corrective_action_process")


# ── Request builder ──────────────────────────────────────────────────

def test_build_ai_request_shapes_center_neighbors_documents_kpis():
    center, neighbors, documents, kpis = kg_ai._build_ai_request(_payload())
    assert center["graph_key"] == "process:corrective_action_process"
    keys = {n["graph_key"] for n in neighbors}
    assert "kpi:on_time_closure" in keys
    # KPI + datasource + query + dashboard are present as related sources.
    assert kpis  # at least the On-time Closure KPI
    assert any(d["title"] == "Quality Manual" for d in documents)


def test_build_ai_request_carries_relationship_and_direction():
    _c, neighbors, _d, _k = kg_ai._build_ai_request(_payload())
    by_label = {n["label"]: n for n in neighbors}
    # policy -> process means, from the center's view, the policy points IN.
    assert by_label["Quality Manual"]["relationship"] == "governs"
    assert by_label["Quality Manual"]["direction"] == "in"
    # process -> kpi points OUT.
    assert by_label["On-time Closure"]["direction"] == "out"


# ── Card mapper (evidence gate) ──────────────────────────────────────

def test_map_card_grounds_in_real_nodes_and_buckets_sources():
    payload = _payload()
    center = payload["centerNode"]
    nodes_by_key = {n["graphKey"]: n for n in payload["nodes"]}
    raw = {
        "id": "c1",
        "category": "risk",
        "severity": "urgent",
        "title": "CAPA closures slipping",
        "summary": "Open CAPAs trending up against policy.",
        "confidence": 0.9,
        "evidenceKeys": ["policy:3", "kpi:on_time_closure", "datasource:capa_table"],
        "recommendedAction": "Review overdue CAPAs weekly.",
    }
    card = kg_ai._map_card(raw, index=0, center=center, nodes_by_key=nodes_by_key, edges=payload["edges"])
    assert card is not None
    assert card["category"] == "risk"
    assert card["sourceDocuments"] == ["Quality Manual"]
    assert card["supportedKpis"] == ["On-time Closure"]
    assert card["sourceTables"] == ["capa_table"]
    assert card["aiGenerated"] is True
    assert card["traceToEvidence"]["nodeKeys"] == card["evidencePath"]
    assert center["id"] in card["traceToEvidence"]["nodeIds"]


def test_map_card_rejects_fabricated_evidence():
    payload = _payload()
    center = payload["centerNode"]
    nodes_by_key = {n["graphKey"]: n for n in payload["nodes"]}
    raw = {"id": "c2", "title": "Invented", "evidenceKeys": ["kpi:does_not_exist"]}
    assert kg_ai._map_card(raw, index=0, center=center, nodes_by_key=nodes_by_key, edges=payload["edges"]) is None


# ── End-to-end enrichment ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_enrich_replaces_cards_when_ai_returns_grounded_cards(monkeypatch):
    monkeypatch.setattr(kg_ai.ai, "is_enabled", lambda: True)

    async def _fake_cards(**kwargs):
        return [
            {
                "id": "c1",
                "category": "risk",
                "severity": "urgent",
                "title": "AI risk",
                "summary": "Grounded in real nodes.",
                "confidence": 0.91,
                "evidenceKeys": ["kpi:on_time_closure"],
            }
        ]

    monkeypatch.setattr(kg_ai.ai, "knowledge_graph_cards", _fake_cards)

    payload = _payload()
    out = await kg_ai.enrich_payload_with_ai(payload, tenant_id=1, user_id=2, project_id=7)
    assert out["aiGenerated"] is True
    assert out["pipeline_version"] == kg_ai.PIPELINE_VERSION_AI
    assert any(c["title"] == "AI risk" and c.get("aiGenerated") for c in out["insightCards"])
    # Every AI card produced a trace path.
    assert out["tracePaths"]


@pytest.mark.asyncio
async def test_enrich_falls_back_when_ai_unavailable(monkeypatch):
    monkeypatch.setattr(kg_ai.ai, "is_enabled", lambda: True)

    async def _none(**kwargs):
        return None

    monkeypatch.setattr(kg_ai.ai, "knowledge_graph_cards", _none)
    payload = _payload()
    before = payload["insightCards"]
    out = await kg_ai.enrich_payload_with_ai(payload, tenant_id=1, user_id=2, project_id=7)
    assert out["insightCards"] == before
    assert "aiGenerated" not in out or out.get("aiGenerated") is not True


@pytest.mark.asyncio
async def test_enrich_skipped_when_ai_disabled(monkeypatch):
    monkeypatch.setattr(kg_ai.ai, "is_enabled", lambda: False)
    called = False

    async def _should_not_run(**kwargs):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(kg_ai.ai, "knowledge_graph_cards", _should_not_run)
    payload = _payload()
    out = await kg_ai.enrich_payload_with_ai(payload, tenant_id=1, user_id=2, project_id=7)
    assert called is False
    assert out is payload
