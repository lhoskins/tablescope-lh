"""The intelligence planner must treat cross-table (relationship) analyses as
additive: the parser budget is ``target_count + per_pair * len(relationship_hints)``
so evidence-backed joins the prompt mandates are never truncated off.

Run from ``tablescope-ai-api``: ``pytest -q tests/test_intelligence_plan_budget.py``.
"""

from __future__ import annotations

import asyncio
import json

import pytest

import app.routers.ai as ai
from app.models.schemas import IntelligencePlanRequest


def _hint(i: int) -> dict:
    return {
        "left_table": f"a{i}",
        "right_table": f"b{i}",
        "left_join_key": "k",
        "right_join_key": "k",
        "relationship_type": "one_to_many",
        "join_confidence": 0.8,
        "confidence_reason": "measured",
        "row_multiplication_risk": "low",
    }


def _plan_json(n: int) -> str:
    # Document-grounded analyses (empty SQL) so none are dropped by SQL
    # validation — the test isolates the slice budget, not SQL shape.
    return json.dumps(
        {
            "analyses": [
                {
                    "id": f"a{i}",
                    "category": "trend",
                    "title": f"Analysis {i}",
                    "rationale": "why",
                    "sql": "",
                    "chart_type": "none",
                    "source_documents": ["Doc"],
                }
                for i in range(n)
            ]
        }
    )


@pytest.fixture(autouse=True)
def _patch_endpoint(monkeypatch):
    monkeypatch.setattr(ai, "verify_signature", lambda *a, **k: None)

    async def fake_build_context(**kwargs):
        return object()

    monkeypatch.setattr(ai.context_builder, "build_context", fake_build_context)
    monkeypatch.setattr(
        ai.context_builder, "context_to_prompt_text", lambda ctx: ""
    )
    monkeypatch.setattr(ai, "update_activity", lambda *a, **k: None)


def _req(hints: list[dict]) -> IntelligencePlanRequest:
    return IntelligencePlanRequest(
        tenant_id=1,
        user_id=1,
        project_id=1,
        allowed_tables=["spend"],
        table_schema=[
            {
                "table": "spend",
                "columns": [
                    {"name": "supplier", "type": "string"},
                    {"name": "amount", "type": "number"},
                ],
            }
        ],
        documents=[{"title": "Doc", "summary": "s"}],
        relationship_hints=hints,
        max_analyses=50,
        granularity=3,  # target_count = 8
    )


def test_plan_budget_keeps_extra_join_analyses(monkeypatch):
    # 11 analyses; with 3 hints at granularity 3 the budget is
    # 8 + 2*3 = 14, so none are sliced off.
    async def fake_generate(**kwargs):
        return _plan_json(11)

    monkeypatch.setattr(ai.llm_client, "generate", fake_generate)

    resp = asyncio.run(ai.intelligence_plan(_req([_hint(0), _hint(1), _hint(2)])))
    assert len(resp.analyses) == 11


def test_plan_budget_unchanged_without_hints(monkeypatch):
    # 0 hints → budget stays at target_count (8): an 11-analysis plan is
    # truncated to 8, identical to the pre-change behavior.
    async def fake_generate(**kwargs):
        return _plan_json(11)

    monkeypatch.setattr(ai.llm_client, "generate", fake_generate)

    resp = asyncio.run(ai.intelligence_plan(_req([])))
    assert len(resp.analyses) == 8
