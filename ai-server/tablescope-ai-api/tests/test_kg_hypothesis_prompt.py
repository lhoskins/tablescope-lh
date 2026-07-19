"""Tests for the Knowledge Graph hypotheses block in the intelligence plan prompt.

Run from the ``tablescope-ai-api`` directory: ``pytest -q``.
"""

from __future__ import annotations

from app.models.schemas import IntelligencePlanRequest
from app.routers.ai import _build_kg_hypothesis_lines

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
