"""Plan-call determinism (content-derived seed) and the combo chart vocabulary.

1. The intelligence plan call must run deterministically: temperature 0.0 with a
   seed derived from tenant/project/granularity + a fingerprint of the schema,
   relationship evidence, and documents. The same context yields the same seed;
   changing the context (or granularity) yields a different one, so a refresh
   only re-plans when something actually changed.
2. ``combo`` (bars + overlay line, e.g. plan vs actuals) must be an allowed plan
   chart type and appear in the planner's chart vocabulary.

Run from ``tablescope-ai-api``: ``pytest -q tests/test_plan_determinism_and_combo.py``.
"""

from __future__ import annotations

import asyncio
import json

import pytest

import app.routers.ai as ai
from app.models.schemas import IntelligencePlanRequest


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


def _capture_generate(monkeypatch, response: str) -> dict:
    captured: dict = {}

    async def fake_generate(**kwargs):
        captured.update(kwargs)
        return response

    monkeypatch.setattr(ai.llm_client, "generate", fake_generate)
    return captured


def _req(
    *,
    project_id: int = 1,
    granularity: int = 3,
    columns: list[dict] | None = None,
) -> IntelligencePlanRequest:
    return IntelligencePlanRequest(
        tenant_id=1,
        user_id=1,
        project_id=project_id,
        allowed_tables=["spend"],
        table_schema=[
            {
                "table": "spend",
                "columns": columns
                or [
                    {"name": "supplier", "type": "string"},
                    {"name": "amount", "type": "number"},
                ],
            }
        ],
        documents=[{"title": "Doc", "summary": "s"}],
        relationship_hints=[],
        max_analyses=50,
        granularity=granularity,
    )


_PLAN_JSON = json.dumps(
    {
        "analyses": [
            {
                "id": "s0",
                "category": "trend",
                "title": "Single",
                "rationale": "why",
                "sql": "",
                "chart_type": "none",
                "source_documents": ["Doc"],
            }
        ]
    }
)


# ── 1. Deterministic seed ────────────────────────────────────────────────────

def test_plan_call_is_deterministic(monkeypatch):
    captured = _capture_generate(monkeypatch, _PLAN_JSON)
    asyncio.run(ai.intelligence_plan(_req()))
    assert captured["temperature"] == 0.0
    assert isinstance(captured["seed"], int)


def test_same_context_yields_same_seed(monkeypatch):
    captured = _capture_generate(monkeypatch, _PLAN_JSON)
    asyncio.run(ai.intelligence_plan(_req()))
    first = captured["seed"]
    asyncio.run(ai.intelligence_plan(_req()))
    assert captured["seed"] == first


def test_different_schema_yields_different_seed(monkeypatch):
    captured = _capture_generate(monkeypatch, _PLAN_JSON)
    asyncio.run(ai.intelligence_plan(_req()))
    base = captured["seed"]
    asyncio.run(
        ai.intelligence_plan(
            _req(
                columns=[
                    {"name": "supplier", "type": "string"},
                    {"name": "amount", "type": "number"},
                    {"name": "region", "type": "string"},
                ]
            )
        )
    )
    assert captured["seed"] != base


def test_different_granularity_yields_different_seed(monkeypatch):
    captured = _capture_generate(monkeypatch, _PLAN_JSON)
    asyncio.run(ai.intelligence_plan(_req(granularity=3)))
    g3 = captured["seed"]
    asyncio.run(ai.intelligence_plan(_req(granularity=5)))
    assert captured["seed"] != g3


# ── 2. combo chart vocabulary ────────────────────────────────────────────────

def test_combo_is_allowed_plan_chart_type():
    assert "combo" in ai._ALLOWED_PLAN_CHART_TYPES


def test_combo_in_plan_prompt_vocabulary(monkeypatch):
    captured = _capture_generate(monkeypatch, _PLAN_JSON)
    asyncio.run(ai.intelligence_plan(_req()))
    prompt = captured["prompt"]
    assert "combo" in prompt
    assert "|combo|" in prompt  # present in the chart_type enum line


def test_combo_chart_type_survives_parser(monkeypatch):
    plan = json.dumps(
        {
            "analyses": [
                {
                    "id": "c0",
                    "category": "trend",
                    "title": "Plan vs actuals",
                    "rationale": "why",
                    "sql": 'SELECT "period" AS Period, "amount" AS A '
                    'FROM "spend" GROUP BY "period"',
                    "chart_type": "combo",
                    "label_column": "Period",
                    "value_column": "A",
                    "value_column_2": "A",
                }
            ]
        }
    )
    _capture_generate(monkeypatch, plan)
    resp = asyncio.run(ai.intelligence_plan(_req()))
    assert resp.analyses
    assert resp.analyses[0].chart_type == "combo"
