"""The standalone /query/generate pipeline (ai_query_generate.py -> llm_client)
never received the dashboard pipeline's relationship-hint / join-exception
support (see test_dashboard_multitable_prompt.py for the dashboard side of
this). Without it, a query needing measures from two related tables (e.g.
revenue vs. backlog by month) could never be written correctly, and the
model had no signal that JOINs were off-limits by default.

Run from ``tablescope-ai-api``:
``pytest -q tests/test_query_generate_multitable_prompt.py``.
"""

from __future__ import annotations

import asyncio

import pytest

import app.routers.ai_query_generate as ai_query_generate
from app.models.schemas import GenerateSQLRequest


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
    monkeypatch.setattr(ai_query_generate, "verify_signature", lambda *a, **k: None)

    async def fake_build_context(**kwargs):
        class _Ctx:
            allowed_context = {"metadata": []}

        return _Ctx()

    monkeypatch.setattr(
        ai_query_generate.context_builder, "build_context", fake_build_context
    )
    monkeypatch.setattr(ai_query_generate, "update_activity", lambda *a, **k: None)
    # Skip the validate/repair loop entirely -- this test only cares what
    # gets sent to the model, not the validation pipeline.
    monkeypatch.setattr(ai_query_generate, "validate_sql", lambda *a, **k: None)


def _capture_generate(monkeypatch, response: str) -> dict:
    captured: dict = {}

    async def fake_generate(**kwargs):
        captured.update(kwargs)
        return response

    monkeypatch.setattr(ai_query_generate.llm_client, "generate", fake_generate)
    return captured


def _req(hints: list[dict]) -> GenerateSQLRequest:
    return GenerateSQLRequest(
        tenant_id=1,
        user_id=1,
        project_id=1,
        prompt="revenue vs backlog by month",
        allowed_tables=["sales_revenue_monthly", "sales_bookings_forecast_monthly"],
        relationship_hints=hints,
    )


def test_join_exception_rules_when_hints_present(monkeypatch):
    captured = _capture_generate(
        monkeypatch, 'SELECT "Month" FROM "sales_revenue_monthly"'
    )
    asyncio.run(ai_query_generate.generate_sql_endpoint(_req([_hint()])))
    prompt = captured["system_prompt"]
    assert "Do NOT write JOINs" not in prompt
    assert "with ONE exception" in prompt
    assert "MUST build on" in prompt  # directive evidence header
    assert "sales_revenue_monthly" in prompt and "sales_bookings_forecast_monthly" in prompt


def test_single_table_rules_unchanged_without_hints(monkeypatch):
    captured = _capture_generate(
        monkeypatch, 'SELECT "Month" FROM "sales_revenue_monthly"'
    )
    asyncio.run(ai_query_generate.generate_sql_endpoint(_req([])))
    prompt = captured["system_prompt"]
    assert "Do NOT write JOINs" in prompt
    assert "with ONE exception" not in prompt
    assert "RELATIONSHIP EVIDENCE —" not in prompt


def test_currency_and_nl_translation_rules_always_present(monkeypatch):
    captured = _capture_generate(
        monkeypatch, 'SELECT "Month" FROM "sales_revenue_monthly"'
    )
    asyncio.run(ai_query_generate.generate_sql_endpoint(_req([])))
    prompt = captured["system_prompt"]
    assert "alias that column so its name reflects" in prompt
    assert "group by X" in prompt
    assert "CASE WHEN" in prompt
