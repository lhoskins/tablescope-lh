"""_fit_plan_prompt must trim an oversized prompt to fit vLLM's context
window, reserving real room for the output -- and every planner prompt that
can grow large on a big project (dashboard suggest included) must actually
call it with an explicit, matching max_tokens passed to llm_client.generate.

Without this, a project with an inflated context (many saved queries /
dashboards / scopes / junk datasources) fills the whole context window with
prompt, leaving a reasoning model just enough completion budget to think and
none to answer -- reproduced live: 0 widgets, every time, on such a project,
with no error to explain why.

Run from ``tablescope-ai-api``: ``pytest -q tests/test_fit_plan_prompt.py``.
"""

from __future__ import annotations

import asyncio
import json

import pytest

import app.routers.ai_dashboard as ai_dashboard
from app.models.schemas import SuggestDashboardRequest, SuggestDashboardsMultiRequest
from app.routers.ai_plan_prompt import _fit_plan_prompt


def test_short_prompt_is_returned_unchanged():
    prompt = "Allowed tables: a, b\n\nDescribe a dashboard."
    assert _fit_plan_prompt(prompt, "system", max_model_len=12288) == prompt


def test_oversized_prompt_is_trimmed_to_fit_the_budget():
    system_prompt = "system rules " * 20  # ~260 chars
    tail = "\n\nOUTPUT FORMAT: respond with JSON only."
    huge_context = "context line filled with project data. " * 5000  # ~205k chars
    prompt = huge_context + tail

    fitted = _fit_plan_prompt(
        prompt, system_prompt, max_model_len=12288, max_tokens=2048, chars_per_token=3.5,
    )

    assert len(fitted) < len(prompt)
    assert fitted.endswith(tail.strip()) or tail.strip() in fitted
    assert fitted.startswith("[context truncated for length]")


def test_trim_leaves_room_for_the_reserved_output_tokens():
    system_prompt = "s" * 350
    prompt = "x" * 100_000
    max_model_len = 12288
    max_tokens = 2048
    chars_per_token = 3.5

    fitted = _fit_plan_prompt(
        prompt, system_prompt, max_model_len=max_model_len,
        max_tokens=max_tokens, chars_per_token=chars_per_token,
    )

    reserve_tokens = max_tokens + int(len(system_prompt) / chars_per_token) + 40
    token_budget = max_model_len - reserve_tokens
    char_budget = int(token_budget * chars_per_token)
    # Fitted text (minus the truncation marker) must not exceed the budget.
    body = fitted.removeprefix("[context truncated for length]\n\n")
    assert len(body) <= char_budget


# ── ai_dashboard.py actually calls it with a matching max_tokens ───────────

@pytest.fixture(autouse=True)
def _patch_endpoint(monkeypatch):
    monkeypatch.setattr(ai_dashboard, "verify_signature", lambda *a, **k: None)

    async def fake_build_context(**kwargs):
        class _Ctx:
            allowed_context = {"metadata": []}

        return _Ctx()

    # A single oversized block simulates a project whose real context (many
    # saved queries/dashboards/scopes/datasources) is large enough to starve
    # a reasoning model of completion room if never trimmed.
    huge_context_text = "project context row. " * 6000  # ~132k chars

    monkeypatch.setattr(ai_dashboard.context_builder, "build_context", fake_build_context)
    monkeypatch.setattr(
        ai_dashboard.context_builder, "context_to_prompt_text", lambda ctx: huge_context_text
    )
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


_SUGGEST_RESPONSE = json.dumps(
    {
        "title": "t", "description": "d", "business_domain": "sales",
        "intended_audience": "executive", "executive_summary": "s", "widgets": [],
    }
)
_SUGGEST_MULTI_RESPONSE = json.dumps({"suggestions": []})


def test_suggest_dashboard_trims_an_oversized_prompt_and_reserves_output_tokens(monkeypatch):
    captured = _capture_generate(monkeypatch, _SUGGEST_RESPONSE)
    req = SuggestDashboardRequest(
        tenant_id=1, user_id=1, project_id=1, allowed_tables=["a", "b"],
    )

    asyncio.run(ai_dashboard.suggest_dashboard(req))

    assert captured["max_tokens"] == 2048
    assert captured["prompt"].startswith("[context truncated for length]")
    assert len(captured["prompt"]) < 132_000


def test_suggest_dashboards_multi_trims_an_oversized_prompt_and_reserves_output_tokens(monkeypatch):
    captured = _capture_generate(monkeypatch, _SUGGEST_MULTI_RESPONSE)
    req = SuggestDashboardsMultiRequest(
        tenant_id=1, user_id=1, project_id=1, allowed_tables=["a", "b"],
    )

    asyncio.run(ai_dashboard.suggest_dashboards_multi(req))

    assert captured["max_tokens"] == 2048
    assert captured["prompt"].startswith("[context truncated for length]")
    assert len(captured["prompt"]) < 132_000


def test_suggest_dashboard_leaves_a_small_prompt_unchanged(monkeypatch):
    monkeypatch.setattr(
        ai_dashboard.context_builder, "context_to_prompt_text", lambda ctx: "small context"
    )
    captured = _capture_generate(monkeypatch, _SUGGEST_RESPONSE)
    req = SuggestDashboardRequest(
        tenant_id=1, user_id=1, project_id=1, allowed_tables=["a", "b"],
    )

    asyncio.run(ai_dashboard.suggest_dashboard(req))

    assert captured["max_tokens"] == 2048
    assert not captured["prompt"].startswith("[context truncated for length]")
