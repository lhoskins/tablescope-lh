"""KG-40: a safe deterministic fallback for KG insight cards.

Validated gap: AI card generation cleared ``insightCards``/``tracePaths`` to
an empty list whenever the AI service was disabled, unreachable, or
rejected every result -- discarding the deterministic, evidence-grounded
structural cards ``build_graph_payload`` had *already computed into the
same payload* moments earlier. The read path (serving a cached snapshot
with no AI bundle for the requested center) did the same thing. Neither
path fabricated recommendations; both simply threw away real,
already-computed evidence relationships instead of showing them.

``tests/test_knowledge_graph_ai.py`` covers the AI-enrichment-pipeline
side (``enrich_payload_with_ai``/``_clear_cards``). This file covers the
separate snapshot-read path (``build_node_centric_graph_from_snapshot``,
no cached bundle for the requested center).

Run from ``platform-api``:
``pytest -q tests/test_kg40_deterministic_card_fallback.py``.
"""

from __future__ import annotations

from app.services.knowledge_graph_builder import (
    build_graph_payload,
    build_node_centric_graph_from_snapshot,
)


def _nodes() -> list[dict]:
    return [
        {"id": 1, "node_type": "project", "name": "Proj", "source_type": None, "source_id": None, "properties": {"project_id": 7}},
        {"id": 2, "node_type": "process", "name": "Corrective Action Process", "source_type": None, "source_id": None, "properties": {"confidence": 0.95, "summary": "CAPA workflow."}},
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


def _full_snapshot(**overrides) -> dict:
    snap = {
        "id": 1,
        "fullGraph": {"nodes": _nodes(), "edges": _edges()},
        "generatedAt": "2026-01-01T00:00:00+00:00",
        "aiCardsByCenter": {},
    }
    snap.update(overrides)
    return snap


def test_no_cached_bundle_falls_back_to_structural_cards():
    structural = build_graph_payload(_nodes(), _edges(), center_node="process:corrective_action_process")
    assert structural["insightCards"], "fixture must yield a structural card to make this test meaningful"

    payload = build_node_centric_graph_from_snapshot(
        _full_snapshot(), center_node="process:corrective_action_process",
    )
    assert payload["insightCards"] == structural["insightCards"]
    assert payload["aiGenerated"] is False
    assert payload["aiEnrichmentStatus"] == "unavailable"


def test_cached_ai_bundle_still_overrides_the_structural_fallback():
    default = build_graph_payload(_nodes(), _edges(), center_node="process:corrective_action_process")
    center_key = default["centerNode"]["graphKey"]
    ai_cards = [{"id": "ai-1", "category": "risk", "title": "AI risk"}]
    snap = _full_snapshot(aiCardsByCenter={
        center_key: {
            "insightCards": ai_cards, "gaps": [], "recommendedActions": [],
            "tracePaths": [], "aiGenerated": True, "aiEnrichmentStatus": "ok",
        }
    })
    payload = build_node_centric_graph_from_snapshot(snap, center_node=center_key)
    assert payload["insightCards"] == ai_cards
    assert payload["aiGenerated"] is True
    assert payload["aiEnrichmentStatus"] == "ok"


def test_a_cached_fallback_bundle_is_served_as_is_on_a_later_read():
    """A precache run that itself fell back to structural cards persists
    aiEnrichmentStatus='unavailable' in the bundle -- a later read must
    still show those (real, grounded) cards, not re-clear them."""
    default = build_graph_payload(_nodes(), _edges(), center_node="process:corrective_action_process")
    center_key = default["centerNode"]["graphKey"]
    fallback_cards = default["insightCards"]
    snap = _full_snapshot(aiCardsByCenter={
        center_key: {
            "insightCards": fallback_cards, "gaps": [], "recommendedActions": [],
            "tracePaths": [], "aiGenerated": False, "aiEnrichmentStatus": "unavailable",
        }
    })
    payload = build_node_centric_graph_from_snapshot(snap, center_node=center_key)
    assert payload["insightCards"] == fallback_cards
    assert payload["aiGenerated"] is False
    assert payload["aiEnrichmentStatus"] == "unavailable"
