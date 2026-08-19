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


# ── Regression: the user's actual request must survive trimming ────────────
#
# The first version of this fix positioned `user_instruction` (rendered from
# req.prompt -- e.g. a user-named list of specific charts, "Monthly Revenue
# (bar) vs Monthly backlog (line)") near the FRONT of the prompt, right after
# context_text/kg/best-practices. _fit_plan_prompt trims from the front and
# keeps the tail, so on a large project that combination silently dropped the
# user's actual request while every fixed instruction/schema block at the
# tail survived untouched -- the model saw no named charts at all and fell
# back to generic ones. Confirmed live: "Requested 5 charts; AI proposed 5"
# but only 2 of 5 -- neither the requested combo chart -- reached the final
# dashboard. Fixed by moving user_instruction to sit immediately before the
# JSON-schema tail, which is unconditionally preserved by the trim.

_NAMED_CHART_REQUEST = (
    "Monthly Revenue||Total Revenu KPI card||Total Backlog KPI card||"
    "Monthly Revenue (bar) vs Monthly backlog (line)||Monthly Backlog"
)


# _fit_plan_prompt always trims from the front and keeps a fixed-size SUFFIX
# (char_budget characters counted from the end). So the safety of a block's
# position is entirely determined by how many characters follow it -- that
# distance-from-end never changes no matter how much front content (a huge
# project's context_text) is added. Using a small, untrimmed context here and
# asserting that distance directly proves survival for ANY context size,
# rather than depending on hitting a specific truncation boundary by luck.
_SAFE_TAIL_DISTANCE = 5000  # generous margin under the ~34.9k char_budget
# the default settings (max_tokens=2048, vllm_max_model_len=12288) reserve.


def test_suggest_dashboard_places_the_user_request_within_the_safe_tail(monkeypatch):
    captured = _capture_generate(monkeypatch, _SUGGEST_RESPONSE)
    req = SuggestDashboardRequest(
        tenant_id=1, user_id=1, project_id=1, allowed_tables=["a", "b"],
        prompt=_NAMED_CHART_REQUEST,
    )

    asyncio.run(ai_dashboard.suggest_dashboard(req))

    prompt = captured["prompt"]
    idx = prompt.index(_NAMED_CHART_REQUEST)
    assert len(prompt) - idx < _SAFE_TAIL_DISTANCE


def test_suggest_dashboards_multi_places_the_user_request_within_the_safe_tail(monkeypatch):
    captured = _capture_generate(monkeypatch, _SUGGEST_MULTI_RESPONSE)
    req = SuggestDashboardsMultiRequest(
        tenant_id=1, user_id=1, project_id=1, allowed_tables=["a", "b"],
        prompt=_NAMED_CHART_REQUEST,
    )

    asyncio.run(ai_dashboard.suggest_dashboards_multi(req))

    prompt = captured["prompt"]
    idx = prompt.index(_NAMED_CHART_REQUEST)
    assert len(prompt) - idx < _SAFE_TAIL_DISTANCE


# ── best_practices_block must be sacrificed before context_text ────────────
#
# dashboard_best_practices.md is ~19k chars (~5.5k tokens) -- over half of
# the ~34.9k char_budget the default settings leave after reserving output.
# It used to sit ahead of context_text, so a front-trim protected 19k chars
# of static, identical-every-call reference text while cutting into the
# project's actual per-request schema first -- backwards, since the model
# cannot write correct SQL for a source it never saw the columns for.
# Reordered so context_text (what SPECIFIC columns this project's sources
# have) outranks best_practices_block (generic policy) when something has
# to give.

def test_suggest_dashboard_sacrifices_best_practices_before_project_schema(monkeypatch):
    monkeypatch.setattr(
        ai_dashboard, "load_prompt_reference",
        lambda *a, **k: "BP_MARKER_START " + ("x" * 40_000),
    )
    monkeypatch.setattr(
        ai_dashboard.context_builder, "context_to_prompt_text",
        lambda ctx: "CTX_MARKER_START " + ("y" * 3_000),
    )
    captured = _capture_generate(monkeypatch, _SUGGEST_RESPONSE)
    req = SuggestDashboardRequest(
        tenant_id=1, user_id=1, project_id=1, allowed_tables=["a", "b"],
    )

    asyncio.run(ai_dashboard.suggest_dashboard(req))

    prompt = captured["prompt"]
    assert "BP_MARKER_START" not in prompt
    assert "CTX_MARKER_START" in prompt


def test_suggest_dashboards_multi_sacrifices_best_practices_before_project_schema(monkeypatch):
    monkeypatch.setattr(
        ai_dashboard, "load_prompt_reference",
        lambda *a, **k: "BP_MARKER_START " + ("x" * 40_000),
    )
    monkeypatch.setattr(
        ai_dashboard.context_builder, "context_to_prompt_text",
        lambda ctx: "CTX_MARKER_START " + ("y" * 3_000),
    )
    captured = _capture_generate(monkeypatch, _SUGGEST_MULTI_RESPONSE)
    req = SuggestDashboardsMultiRequest(
        tenant_id=1, user_id=1, project_id=1, allowed_tables=["a", "b"],
    )

    asyncio.run(ai_dashboard.suggest_dashboards_multi(req))

    prompt = captured["prompt"]
    assert "BP_MARKER_START" not in prompt
    assert "CTX_MARKER_START" in prompt
