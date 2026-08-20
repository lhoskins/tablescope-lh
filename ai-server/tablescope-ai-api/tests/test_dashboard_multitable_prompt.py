"""The dashboard-suggestion prompts must be internally consistent about
cross-table joins, mirroring test_multitable_plan_prompt.py's coverage of
/ai/intelligence/plan for the two dashboard-suggestion endpoints
(/dashboard/suggest and /dashboard/suggest-multi):

Both previously either forbade JOINs outright or never mentioned
relationships at all, so a widget needing measures from two separate
sources (e.g. actual revenue vs. a forecast in another table) could never
be written correctly. With relationship evidence present, the rules must
switch to the join-exception variant and stay byte-identical to the
single-table original when there is none.

Run from ``tablescope-ai-api``: ``pytest -q tests/test_dashboard_multitable_prompt.py``.
"""

from __future__ import annotations

import asyncio
import json

import pytest

import app.routers.ai_dashboard as ai_dashboard
from app.models.schemas import SuggestDashboardRequest, SuggestDashboardsMultiRequest


def _hint() -> dict:
    return {
        "left_table": "sales_revenue_monthly",
        "right_table": "sales_bookings_forecast_monthly",
        "left_join_key": "month",
        "right_join_key": "month",
        "relationship_type": "one_to_one",
        "join_confidence": 0.5,
        "confidence_reason": "shared reporting-period column 'month'",
        "row_multiplication_risk": "unknown",
    }


@pytest.fixture(autouse=True)
def _patch_endpoint(monkeypatch):
    monkeypatch.setattr(ai_dashboard, "verify_signature", lambda *a, **k: None)

    async def fake_build_context(**kwargs):
        class _Ctx:
            allowed_context = {"metadata": []}

        return _Ctx()

    monkeypatch.setattr(ai_dashboard.context_builder, "build_context", fake_build_context)
    monkeypatch.setattr(ai_dashboard.context_builder, "context_to_prompt_text", lambda ctx: "")
    monkeypatch.setattr(ai_dashboard, "update_activity", lambda *a, **k: None)
    monkeypatch.setattr(ai_dashboard, "load_prompt_reference", lambda *a, **k: "")
    monkeypatch.setattr(ai_dashboard, "format_knowledge_graph_context", lambda *a, **k: "")


def _capture_generate(monkeypatch, response: str) -> dict:
    captured: dict = {}

    async def fake_generate(**kwargs):
        captured.update(kwargs)
        return response

    monkeypatch.setattr(ai_dashboard.llm_client, "generate", fake_generate)
    return captured


def _suggest_req(hints: list[dict]) -> SuggestDashboardRequest:
    return SuggestDashboardRequest(
        tenant_id=1,
        user_id=1,
        project_id=1,
        allowed_tables=["sales_revenue_monthly", "sales_bookings_forecast_monthly"],
        relationship_hints=hints,
    )


def _suggest_multi_req(hints: list[dict]) -> SuggestDashboardsMultiRequest:
    return SuggestDashboardsMultiRequest(
        tenant_id=1,
        user_id=1,
        project_id=1,
        allowed_tables=["sales_revenue_monthly", "sales_bookings_forecast_monthly"],
        relationship_hints=hints,
    )


_SUGGEST_RESPONSE = json.dumps(
    {
        "title": "Revenue Health",
        "description": "d",
        "business_domain": "sales",
        "intended_audience": "executive",
        "executive_summary": "s",
        "widgets": [],
    }
)

_SUGGEST_MULTI_RESPONSE = json.dumps(
    {
        "suggestions": [
            {
                "title": "Revenue Health",
                "description": "d",
                "business_purpose": "p",
                "audience": "executive",
                "widgets": [],
                "kpis": [],
                "confidence": 0.8,
                "quality_score": 90,
            }
        ]
    }
)


# ── /dashboard/suggest ──────────────────────────────────────────────────────

def test_suggest_join_exception_rules_when_hints_present(monkeypatch):
    captured = _capture_generate(monkeypatch, _SUGGEST_RESPONSE)
    asyncio.run(ai_dashboard.suggest_dashboard(_suggest_req([_hint()])))
    prompt = captured["prompt"]
    assert "Do NOT write JOINs" not in prompt
    assert "with ONE exception" in prompt
    assert "MUST build on" in prompt  # directive evidence header
    assert "sales_revenue_monthly" in prompt and "sales_bookings_forecast_monthly" in prompt


def test_suggest_single_table_rules_unchanged_without_hints(monkeypatch):
    captured = _capture_generate(monkeypatch, _SUGGEST_RESPONSE)
    asyncio.run(ai_dashboard.suggest_dashboard(_suggest_req([])))
    prompt = captured["prompt"]
    assert "Do NOT write JOINs" in prompt
    assert "with ONE exception" not in prompt
    assert "RELATIONSHIP EVIDENCE —" not in prompt


# ── /dashboard/suggest-multi ────────────────────────────────────────────────

def test_suggest_multi_join_exception_rules_when_hints_present(monkeypatch):
    captured = _capture_generate(monkeypatch, _SUGGEST_MULTI_RESPONSE)
    asyncio.run(ai_dashboard.suggest_dashboards_multi(_suggest_multi_req([_hint()])))
    prompt = captured["prompt"]
    assert "Do NOT write JOINs" not in prompt
    assert "with ONE exception" in prompt
    assert "MUST build on" in prompt


def test_suggest_multi_single_table_rules_unchanged_without_hints(monkeypatch):
    captured = _capture_generate(monkeypatch, _SUGGEST_MULTI_RESPONSE)
    asyncio.run(ai_dashboard.suggest_dashboards_multi(_suggest_multi_req([])))
    prompt = captured["prompt"]
    assert "Do NOT write JOINs" in prompt
    assert "with ONE exception" not in prompt
    assert "RELATIONSHIP EVIDENCE —" not in prompt
