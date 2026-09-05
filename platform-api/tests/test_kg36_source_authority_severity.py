"""KG-36: weight source authority explicitly, not just project-vs-reference.

Validated gap: ``gate_severity`` capped any risk-grade severity to ``watch``
whenever a card's evidence rested only on ``reference_document`` nodes -- with
no distinction between an authoritative, approved company/project-tier
document and a generic industry reference. The review's own stated
source-authority order ranks "approved company policy" and "project
documentation" above generic "industry references", so a card grounded only
in a company-tier or project-tier reference document should not be capped the
same way as one grounded only in an industry-tier one.

Run from ``platform-api``: ``pytest -q tests/test_kg36_source_authority_severity.py``.
"""

from __future__ import annotations

from app.services import knowledge_graph_ai as kg_ai
from app.services.knowledge_graph_builder import build_graph_payload


def _nodes(tier: str) -> list[dict]:
    return [
        {"id": 1, "node_type": "project", "name": "Proj", "source_type": None, "source_id": None, "properties": {"project_id": 7}},
        {"id": 2, "node_type": "risk", "name": "CAPA Slippage", "source_type": None, "source_id": None, "properties": {"confidence": 0.95, "summary": "CAPA workflow risk.", "graph_key": "risk:capa_slippage"}},
        {"id": 3, "node_type": "reference_document", "name": "Quality Standard", "source_type": "reference_document", "source_id": 30, "properties": {"summary": "Governs CAPA.", "tier": tier}},
    ]


def _edges() -> list[dict]:
    def e(eid, a, b, rel, conf):
        return {"id": eid, "from_node_id": a, "to_node_id": b, "relationship_type": rel, "confidence": conf, "evidence": {}}

    return [
        e(1, 1, 2, "contains", 0.99),
        e(2, 3, 2, "governs", 0.95),
    ]


def _card_for_tier(tier: str) -> dict:
    payload = build_graph_payload(_nodes(tier), _edges(), center_node="risk:capa_slippage")
    center = payload["centerNode"]
    nodes_by_key = {n["graphKey"]: n for n in payload["nodes"]}
    raw = {
        "id": "c1",
        "category": "risk",
        "title": "CAPA closures slipping",
        "severity": "risk",
        "confidence": 0.9,
        "evidenceKeys": ["document:30"],
    }
    card = kg_ai._map_card(
        raw, index=0, center=center, nodes_by_key=nodes_by_key,
        nodes=payload["nodes"], edges=payload["edges"],
    )
    assert card is not None
    return card


def test_industry_tier_only_evidence_is_still_capped_to_watch():
    card = _card_for_tier("industry")
    assert card["severity"] == "watch"


def test_company_tier_only_evidence_is_not_capped():
    card = _card_for_tier("company")
    assert card["severity"] == "risk"


def test_project_tier_only_evidence_is_not_capped():
    card = _card_for_tier("project")
    assert card["severity"] == "risk"
