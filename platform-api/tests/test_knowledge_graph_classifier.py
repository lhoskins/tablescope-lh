"""Unit tests for the knowledge graph relationship classifier."""

from __future__ import annotations

import pytest

from app.services.knowledge_graph.classifier import (
    _classify_relationship,
    _edge_confidence,
    _evidence_summary,
    classify_connector_style,
)


def _edge(
    *,
    relationship_type: str = "uses",
    confidence: float = 0.95,
    validation_status: str = "",
    evidence_basis: str = "",
    extra: dict | None = None,
) -> dict:
    evidence: dict = {"validation_status": validation_status, "evidence_basis": evidence_basis}
    if extra:
        evidence.update(extra)
    return {
        "id": 1,
        "relationship_type": relationship_type,
        "confidence": confidence,
        "evidence": evidence,
    }


@pytest.mark.parametrize(
    "relationship_type,validation_status,evidence_basis,confidence,expected",
    [
        # Explicit project evidence → solid, shown.
        ("uses", "validated", "", 0.95, ("explicit", "solid", True, "validated")),
        ("cites", "validated", "", 0.99, ("explicit", "solid", True, "validated")),
        # Inferred with high confidence → dotted, shown.
        ("linked_by_inferred_join", "inferred", "", 0.80, ("inferred", "dotted", True, "inferred")),
        ("mentions", "inferred", "", 0.80, ("inferred", "dotted", True, "inferred")),
        # Inferred below display floor → dotted, hidden by default.
        ("mentions", "inferred", "", 0.60, ("inferred", "dotted", False, "inferred")),
        # Recommended / best-practice relationships → dashed, hidden.
        ("recommended_kpi", "", "", 0.90, ("recommended", "dashed", False, "suggested")),
        ("missing_required_evidence", "", "", 0.90, ("recommended", "dashed", False, "suggested")),
        # Validated relationship forced to suggested by validation status.
        ("uses", "suggested", "", 0.95, ("recommended", "dashed", False, "suggested")),
        # Rejected evidence → hidden.
        ("uses", "rejected", "", 0.95, ("hidden", "hidden", False, "rejected")),
        # Strong-but-not-validated confidence → high-confidence inference.
        ("uses", "", "", 0.85, ("inferred", "dotted", True, "inferred")),
        # Weak confidence → faint dotted.
        ("uses", "", "", 0.55, ("weak", "dotted", False, "weak")),
        # Very low confidence → hidden.
        ("uses", "", "", 0.30, ("hidden", "hidden", False, "rejected")),
    ],
)
def test_classify_connector_style_table(
    relationship_type, validation_status, evidence_basis, confidence, expected
):
    edge = _edge(
        relationship_type=relationship_type,
        confidence=confidence,
        validation_status=validation_status,
        evidence_basis=evidence_basis,
    )
    result = classify_connector_style(edge)
    strength, style, display, vstatus = expected
    assert result["relationshipStrength"] == strength
    assert result["connectorStyle"] == style
    assert result["displayByDefault"] is display
    assert result["validationStatus"] == vstatus


def test_reference_membership_with_explicit_citation_becomes_solid():
    edge = _edge(
        relationship_type="reference",
        confidence=0.95,
        evidence_basis="explicit_citation",
    )
    result = classify_connector_style(edge)
    assert result["relationshipStrength"] == "explicit"
    assert result["connectorStyle"] == "solid"
    assert result["displayByDefault"] is True


def test_reference_membership_with_semantic_inference_becomes_dotted():
    edge = _edge(
        relationship_type="reference",
        confidence=0.80,
        validation_status="inferred",
        evidence_basis="",
    )
    result = classify_connector_style(edge)
    assert result["relationshipStrength"] == "inferred"
    assert result["connectorStyle"] == "dotted"
    assert result["displayByDefault"] is True


def test_reference_membership_without_evidence_is_recommended():
    edge = _edge(relationship_type="reference", confidence=0.95)
    result = classify_connector_style(edge)
    assert result["relationshipStrength"] == "recommended"
    assert result["connectorStyle"] == "dashed"
    assert result["displayByDefault"] is False


def test_kpi_recommended_property_overrides_relationship_type():
    edge = _edge(relationship_type="measures", confidence=0.95, validation_status="validated")
    src = {"type": "kpi", "properties": {"kpiStatus": "recommended"}}
    tgt = {"type": "metric", "properties": {}}
    result = _classify_relationship(edge, src, tgt)
    assert result["relationshipStrength"] == "recommended"
    assert result["connectorStyle"] == "dashed"


def test_edge_confidence_handles_missing_and_invalid_values():
    assert _edge_confidence({"confidence": 0.75}) == 0.75
    assert _edge_confidence({"confidence": "0.5"}) == 0.5
    assert _edge_confidence({"confidence": None}) == 0.0
    assert _edge_confidence({"confidence": "not-a-number"}) == 0.0
    assert _edge_confidence({}) == 0.0


def test_evidence_summary_prefers_explicit_summary_fields():
    assert _evidence_summary({"evidence": {"evidence_summary": "It works"}}) == "It works"
    assert _evidence_summary({"evidence": {"reason": "Because"}}) == "Because"
    assert _evidence_summary({"evidence": {"text": "Raw text"}}) == "Raw text"
    assert _evidence_summary({"evidence": "plain"}) == "plain"
    assert _evidence_summary({}) == ""
