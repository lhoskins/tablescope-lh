"""Tests for the ``/ai/intelligence/investigate-step`` "why" investigation
agent step, and the investigation-aware ``_format_data_result`` rendering
used to synthesize the final answer.

Run from the ``tablescope-ai-api`` directory: ``pytest -q``.
"""

from __future__ import annotations

import asyncio
import json

import pytest

import app.routers.ai as ai
import app.routers.ai_intelligence_investigate_step as investigate_step_module
from app.models.schemas import (
    IntelligenceInvestigateStepRequest,
    InvestigationStepResult,
)
from app.routers.ai_ask import _format_data_result


@pytest.fixture(autouse=True)
def _skip_signature_verification(monkeypatch):
    """See test_repair_sql_step.py's identical fixture: verify_signature no
    longer skips verification for an empty/unset secret (TS-ISO-007), so
    tests that don't set up a real signature must bypass it explicitly."""
    monkeypatch.setattr(investigate_step_module, "verify_signature", lambda *a, **k: None)


def _capture_generate(monkeypatch, response: str) -> dict:
    captured: dict = {}

    async def fake_generate(**kwargs):
        captured.update(kwargs)
        return response

    monkeypatch.setattr(ai.llm_client, "generate", fake_generate)
    return captured


def _req(
    question: str = "Why is the defect rate rising?",
    steps: list[InvestigationStepResult] | None = None,
    steps_remaining: int = 2,
) -> IntelligenceInvestigateStepRequest:
    return IntelligenceInvestigateStepRequest(
        tenant_id=1,
        user_id=1,
        project_id=1,
        question=question,
        steps=steps or [],
        steps_remaining=steps_remaining,
    )


def test_query_action_returns_sub_question(monkeypatch):
    decision = json.dumps({"action": "query", "sub_question": "Defect rate by supplier?"})
    _capture_generate(monkeypatch, decision)
    resp = asyncio.run(ai.intelligence_investigate_step(_req()))
    assert resp.action == "query"
    assert resp.sub_question == "Defect rate by supplier?"


def test_finish_action(monkeypatch):
    _capture_generate(monkeypatch, json.dumps({"action": "finish"}))
    resp = asyncio.run(ai.intelligence_investigate_step(_req()))
    assert resp.action == "finish"
    assert resp.sub_question == ""


def test_repeating_the_original_question_is_coerced_to_finish(monkeypatch):
    decision = json.dumps(
        {"action": "query", "sub_question": "Why is the defect rate rising?"}
    )
    _capture_generate(monkeypatch, decision)
    resp = asyncio.run(ai.intelligence_investigate_step(_req()))
    assert resp.action == "finish"


def test_repeating_a_prior_sub_question_is_coerced_to_finish(monkeypatch):
    prior = [InvestigationStepResult(sub_question="Defect rate by supplier?", row_count=3)]
    decision = json.dumps({"action": "query", "sub_question": "defect rate by supplier?"})
    _capture_generate(monkeypatch, decision)
    resp = asyncio.run(ai.intelligence_investigate_step(_req(steps=prior)))
    assert resp.action == "finish"


def test_query_action_missing_sub_question_is_coerced_to_finish(monkeypatch):
    _capture_generate(monkeypatch, json.dumps({"action": "query", "sub_question": ""}))
    resp = asyncio.run(ai.intelligence_investigate_step(_req()))
    assert resp.action == "finish"


def test_unparseable_response_finishes(monkeypatch):
    _capture_generate(monkeypatch, "I cannot help with that.")
    resp = asyncio.run(ai.intelligence_investigate_step(_req()))
    assert resp.action == "finish"


def test_zero_steps_remaining_finishes_without_calling_the_model(monkeypatch):
    called = {"n": 0}

    async def fake_generate(**kwargs):
        called["n"] += 1
        return json.dumps({"action": "query", "sub_question": "irrelevant"})

    monkeypatch.setattr(ai.llm_client, "generate", fake_generate)
    resp = asyncio.run(ai.intelligence_investigate_step(_req(steps_remaining=0)))
    assert resp.action == "finish"
    assert called["n"] == 0


def test_prior_steps_are_rendered_in_the_prompt(monkeypatch):
    prior = [
        InvestigationStepResult(
            sub_question="Defect rate by supplier?",
            sql='SELECT "Supplier", AVG(CAST("DefectRate" AS double)) AS r FROM "t"',
            columns=["Supplier", "r"],
            row_count=3,
            sample_rows=[{"Supplier": "Acme", "r": 0.12}],
        )
    ]
    captured = _capture_generate(monkeypatch, json.dumps({"action": "finish"}))
    asyncio.run(ai.intelligence_investigate_step(_req(steps=prior)))
    prompt = captured["prompt"]
    assert "Defect rate by supplier?" in prompt
    assert "Acme" in prompt
    assert "row count: 3" in prompt


def test_response_format_json_is_requested(monkeypatch):
    captured = _capture_generate(monkeypatch, json.dumps({"action": "finish"}))
    asyncio.run(ai.intelligence_investigate_step(_req()))
    assert captured["response_format"] == "json"


# --- _format_data_result / investigation rendering ----------------------


def test_format_data_result_renders_investigation_steps_when_present():
    data = {
        "steps": [
            {
                "sub_question": "Defect rate by supplier?",
                "sql": 'SELECT "Supplier" FROM "t"',
                "columns": ["Supplier"],
                "row_count": 2,
                "sample_rows": [{"Supplier": "Acme"}],
                "error": "",
            },
            {
                "sub_question": "Defect rate trend over time?",
                "error": "no matching source",
            },
        ]
    }
    text = _format_data_result("Why is the defect rate rising?", data)
    assert "MULTI-STEP INVESTIGATION" in text
    assert 'Step 1: "Defect rate by supplier?"' in text
    assert "Acme" in text
    assert 'Step 2: "Defect rate trend over time?"' in text
    assert "failed: no matching source" in text


def test_format_data_result_falls_back_to_single_query_rendering_without_steps():
    data = {"sql": 'SELECT 1', "columns": ["x"], "rows": [{"x": 1}], "rowCount": 1}
    text = _format_data_result("How many rows?", data)
    assert "LIVE QUERY RESULT" in text
    assert "MULTI-STEP INVESTIGATION" not in text


def test_format_data_result_ignores_empty_steps_list():
    data = {"steps": [], "sql": "SELECT 1", "columns": ["x"], "rows": [{"x": 1}]}
    text = _format_data_result("q", data)
    assert "LIVE QUERY RESULT" in text
