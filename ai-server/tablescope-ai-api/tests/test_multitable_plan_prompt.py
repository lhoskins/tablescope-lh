"""The plan prompt must be internally consistent about cross-table joins.

Three failure modes this file guards against:

1. With relationship evidence present, the Teiid rules block still said
   "Do NOT write JOINs" — an unconditional rule sitting *later* in the prompt
   than the cross-table mandate, suppressing the joins the mandate asks for.
   The rules must switch to the join-exception variant (and stay byte-identical
   to the single-table original when there is no evidence).
2. When the model overproduces, a blind head-slice cut mandated joins off the
   tail. Single-table and cross-table analyses must each compete only for
   their own budget (``target_count`` vs ``per_pair * len(hints)``).
3. The SQL repair endpoint's rules also said "Do NOT write JOINs", so a failing
   cross-table query was "repaired" into a single-table one. A failing query
   that already joins must be repaired with the keep-the-join rules.

Run from ``tablescope-ai-api``: ``pytest -q tests/test_multitable_plan_prompt.py``.
"""

from __future__ import annotations

import asyncio
import json

import pytest

import app.routers.ai as ai
from app.models.schemas import IntelligenceFixSQLRequest, IntelligencePlanRequest

_JOIN_SQL = (
    'SELECT s."k" AS K, SUM(CAST(d."v" AS double)) AS V '
    'FROM "a0" s JOIN "b0" d ON s."k" = d."k" GROUP BY s."k"'
)


def _hint() -> dict:
    return {
        "left_table": "a0",
        "right_table": "b0",
        "left_join_key": "k",
        "right_join_key": "k",
        "relationship_type": "one_to_many",
        "join_confidence": 0.8,
        "confidence_reason": "measured",
        "row_multiplication_risk": "low",
    }


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


def _req(hints: list[dict], granularity: int = 3) -> IntelligencePlanRequest:
    return IntelligencePlanRequest(
        tenant_id=1,
        user_id=1,
        project_id=1,
        allowed_tables=["spend", "a0", "b0"],
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
        granularity=granularity,
    )


def _doc_analysis(i: int) -> dict:
    return {
        "id": f"s{i}",
        "category": "trend",
        "title": f"Single {i}",
        "rationale": "why",
        "sql": "",
        "chart_type": "none",
        "source_documents": ["Doc"],
    }


def _join_analysis(i: int) -> dict:
    return {
        "id": f"j{i}",
        "category": "relationship",
        "title": f"Join {i}",
        "rationale": "why",
        "sql": _JOIN_SQL,
        "chart_type": "bar",
        "label_column": "K",
        "value_column": "V",
    }


def _plan_json(items: list[dict]) -> str:
    return json.dumps({"analyses": items})


# ── 1. Teiid rules variant ───────────────────────────────────────────────────

def test_join_exception_rules_when_hints_present(monkeypatch):
    captured = _capture_generate(monkeypatch, _plan_json([_doc_analysis(0)]))
    asyncio.run(ai.intelligence_plan(_req([_hint()])))
    prompt = captured["prompt"]
    assert "Do NOT write JOINs" not in prompt
    assert "with ONE exception" in prompt
    assert "MUST build on" in prompt  # directive evidence header


def test_single_table_rules_unchanged_without_hints(monkeypatch):
    captured = _capture_generate(monkeypatch, _plan_json([_doc_analysis(0)]))
    asyncio.run(ai.intelligence_plan(_req([])))
    prompt = captured["prompt"]
    assert "Do NOT write JOINs" in prompt
    assert "with ONE exception" not in prompt
    assert "RELATIONSHIP EVIDENCE —" not in prompt


def test_two_per_pair_at_balanced_granularity(monkeypatch):
    captured = _capture_generate(monkeypatch, _plan_json([_doc_analysis(0)]))
    asyncio.run(ai.intelligence_plan(_req([_hint()], granularity=3)))
    assert "TWO genuinely different" in captured["prompt"]


def test_one_per_pair_at_executive_granularity(monkeypatch):
    captured = _capture_generate(monkeypatch, _plan_json([_doc_analysis(0)]))
    asyncio.run(ai.intelligence_plan(_req([_hint()], granularity=2)))
    assert "TWO genuinely different" not in captured["prompt"]


# ── 2. Overflow slice protects joins ────────────────────────────────────────

def test_overflow_keeps_joins_when_singles_overproduced(monkeypatch):
    # granularity 3 + 1 hint → budget = 8 singles + 2 joins. The model returns
    # 10 singles followed by 2 joins (12 > 10 total budget): the old blind
    # [:budget] slice would cut both joins off the tail; now the joins are
    # kept and the singles are trimmed to target_count.
    items = [_doc_analysis(i) for i in range(10)] + [
        _join_analysis(0), _join_analysis(1),
    ]
    _capture_generate(monkeypatch, _plan_json(items))

    resp = asyncio.run(ai.intelligence_plan(_req([_hint()])))
    ids = [a.id for a in resp.analyses]
    assert "j0" in ids and "j1" in ids
    assert len([i for i in ids if i.startswith("s")]) == 8
    assert len(resp.analyses) == 10


def test_overflow_without_hints_matches_old_slice(monkeypatch):
    # No hints → join budget 0: overproduced singles trim to target_count (8),
    # identical to the pre-change behaviour.
    items = [_doc_analysis(i) for i in range(11)]
    _capture_generate(monkeypatch, _plan_json(items))

    resp = asyncio.run(ai.intelligence_plan(_req([])))
    assert len(resp.analyses) == 8


# ── 3. SQL repair keeps a verified join joined ──────────────────────────────

def _fix_req(sql: str) -> IntelligenceFixSQLRequest:
    return IntelligenceFixSQLRequest(
        tenant_id=1,
        user_id=1,
        project_id=1,
        sql=sql,
        error="TEIID31100 parsing error",
        allowed_tables=["a0", "b0"],
        table_schema=[],
    )


def test_fix_sql_join_repair_uses_keep_join_rules(monkeypatch):
    captured = _capture_generate(monkeypatch, "")
    asyncio.run(ai.intelligence_fix_sql(_fix_req(_JOIN_SQL)))
    prompt = captured["prompt"]
    assert "KEEP the same two tables" in prompt
    assert "Do NOT write JOINs" not in prompt


def test_fix_sql_single_table_repair_unchanged(monkeypatch):
    captured = _capture_generate(monkeypatch, "")
    asyncio.run(
        ai.intelligence_fix_sql(_fix_req('SELECT "k" FROM "a0" GROUP BY "k"'))
    )
    prompt = captured["prompt"]
    assert "Do NOT write JOINs" in prompt
    assert "KEEP the same two tables" not in prompt
