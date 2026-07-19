"""Tests for the Knowledge Graph hypotheses block in the intelligence plan prompt.

Run from the ``tablescope-ai-api`` directory: ``pytest -q``.
"""

from __future__ import annotations

from app.models.schemas import IntelligencePlanRequest
from app.routers.ai import (
    _build_kg_hypothesis_lines,
    _build_relationship_floor_line,
)

KG = {
    "risks": [
        {
            "title": "Supplier concentration",
            "severity": "high",
            "summary": "Top supplier carries 62% of spend.",
        }
    ],
    "gaps": [{"title": "No incident log", "summary": "Process gap."}],
    "opportunities": [],
    "warnings": [],
    "recommended_kpis": [
        {"title": "Defect rate", "summary": "Recommended by QA policy."}
    ],
    "measured_kpis": [{"title": "Revenue", "summary": "Already dashboarded."}],
}


def test_empty_context_leaves_prompt_unchanged() -> None:
    assert _build_kg_hypothesis_lines({}) == ""
    assert _build_kg_hypothesis_lines({"risks": [], "gaps": []}) == ""


def test_renders_hypothesis_framing_and_items() -> None:
    block = _build_kg_hypothesis_lines(KG)
    assert "KNOWLEDGE GRAPH HYPOTHESES" in block
    # The anti-echo-chamber contract must be stated verbatim enough to bind.
    assert "HYPOTHESIS" in block
    assert "NEVER assert a graph item as a finding without a query result" in block
    # Items with severity and summaries render; measured KPIs are excluded
    # (they are already covered by queries/dashboards — nothing to test).
    assert "Supplier concentration [high]: Top supplier carries 62% of spend." in block
    assert "No incident log" in block
    assert "Defect rate" in block
    assert "Revenue" not in block


def test_hypotheses_are_additive_and_never_displace_the_mix() -> None:
    """The regression guard: KG hypotheses must not crowd out complex analyses."""
    block = _build_kg_hypothesis_lines(KG)
    assert "ADDITIVE context only" in block
    assert "must NOT displace" in block
    assert "multi-table" in block
    assert "at most half" in block


def test_items_are_capped_to_five_per_bucket() -> None:
    many = {"risks": [{"title": f"Risk {i}"} for i in range(8)]}
    block = _build_kg_hypothesis_lines(many)
    assert "Risk 4" in block
    assert "Risk 5" not in block


def test_relationship_floor_with_evidence() -> None:
    floor = _build_relationship_floor_line(True, granularity=3)
    assert "at least ONE multi-table relationship analysis" in floor
    assert "REQUIRED output" in floor
    assert "knowledge-graph hypotheses" in floor

    granular = _build_relationship_floor_line(True, granularity=4)
    assert "at least TWO multi-table relationship analyses" in granular


def test_relationship_floor_without_evidence_keeps_single_table_mandate() -> None:
    floor = _build_relationship_floor_line(False, granularity=3)
    assert "single-table relationship analyses" in floor
    assert "required mix" in floor
    assert "multi-table" not in floor


def test_malformed_items_are_skipped() -> None:
    block = _build_kg_hypothesis_lines(
        {"risks": ["not-a-dict", {"summary": "no title"}, {"title": "Real risk"}]}
    )
    assert "Real risk" in block
    assert "no title" not in block


def test_schema_accepts_knowledge_graph_context() -> None:
    req = IntelligencePlanRequest(
        tenant_id=1,
        user_id=1,
        project_id=1,
        signature="x",
        timestamp=0,
        knowledge_graph_context=KG,
    )
    assert req.knowledge_graph_context["risks"][0]["title"] == (
        "Supplier concentration"
    )
    # Default stays an empty dict so older platform callers are unaffected.
    assert (
        IntelligencePlanRequest(
            tenant_id=1, user_id=1, project_id=1, signature="x", timestamp=0
        ).knowledge_graph_context
        == {}
    )
