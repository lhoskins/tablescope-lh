"""Tests for the ``/ai/intelligence/repair-sql-step`` self-repair agent step.

Run from the ``tablescope-ai-api`` directory: ``pytest -q``.
"""

from __future__ import annotations

import asyncio
import json

import app.routers.ai as ai
from app.models.schemas import (
    IntelligenceRepairSQLStepRequest,
    RepairSQLColumnKnowledge,
)


def _capture_generate(monkeypatch, response: str) -> dict:
    captured: dict = {}

    async def fake_generate(**kwargs):
        captured.update(kwargs)
        return response

    monkeypatch.setattr(ai.llm_client, "generate", fake_generate)
    return captured


def _req(
    sql: str = 'SELECT "Status" FROM "a0" GROUP BY "Status"',
    error: str = "TEIID31172 comparison error",
    allowed_tables: list[str] | None = None,
    known_columns: list[RepairSQLColumnKnowledge] | None = None,
) -> IntelligenceRepairSQLStepRequest:
    return IntelligenceRepairSQLStepRequest(
        tenant_id=1,
        user_id=1,
        project_id=1,
        sql=sql,
        error=error,
        allowed_tables=allowed_tables or ["a0"],
        table_schema=[{"table": "a0", "columns": [{"name": "Status", "type": "string"}]}],
        known_columns=known_columns or [],
    )


def test_rewrite_action_returns_cleaned_validated_sql(monkeypatch):
    decision = json.dumps({"action": "rewrite", "sql": 'SELECT "Status" FROM "a0" GROUP BY "Status"'})
    _capture_generate(monkeypatch, decision)
    resp = asyncio.run(ai.intelligence_repair_sql_step(_req()))
    assert resp.action == "rewrite"
    assert resp.sql == 'SELECT "Status" FROM "a0" GROUP BY "Status"'


def test_rewrite_action_with_unauthorized_table_falls_back_to_give_up(monkeypatch):
    """A rewrite that references a table outside allowed_tables must never be
    trusted -- validate_sql rejects it the same way fix-sql does, and the
    step degrades to give_up rather than returning unsafe SQL."""
    decision = json.dumps({"action": "rewrite", "sql": 'SELECT "Status" FROM "not_allowed"'})
    _capture_generate(monkeypatch, decision)
    resp = asyncio.run(ai.intelligence_repair_sql_step(_req()))
    assert resp.action == "give_up"
    assert resp.sql == ""


def test_rewrite_action_with_empty_sql_falls_back_to_give_up(monkeypatch):
    decision = json.dumps({"action": "rewrite", "sql": ""})
    _capture_generate(monkeypatch, decision)
    resp = asyncio.run(ai.intelligence_repair_sql_step(_req()))
    assert resp.action == "give_up"


def test_inspect_column_action_returns_table_and_column(monkeypatch):
    decision = json.dumps({"action": "inspect_column", "table": "a0", "column": "Status"})
    _capture_generate(monkeypatch, decision)
    resp = asyncio.run(ai.intelligence_repair_sql_step(_req()))
    assert resp.action == "inspect_column"
    assert resp.table == "a0"
    assert resp.column == "Status"


def test_inspect_column_action_missing_column_falls_back_to_give_up(monkeypatch):
    decision = json.dumps({"action": "inspect_column", "table": "a0", "column": ""})
    _capture_generate(monkeypatch, decision)
    resp = asyncio.run(ai.intelligence_repair_sql_step(_req()))
    assert resp.action == "give_up"


def test_unknown_action_falls_back_to_give_up(monkeypatch):
    decision = json.dumps({"action": "wander_off_and_do_something_else"})
    _capture_generate(monkeypatch, decision)
    resp = asyncio.run(ai.intelligence_repair_sql_step(_req()))
    assert resp.action == "give_up"


def test_unparseable_response_falls_back_to_give_up(monkeypatch):
    _capture_generate(monkeypatch, "I cannot help with that.")
    resp = asyncio.run(ai.intelligence_repair_sql_step(_req()))
    assert resp.action == "give_up"


def test_known_columns_are_rendered_in_the_prompt(monkeypatch):
    captured = _capture_generate(monkeypatch, json.dumps({"action": "give_up"}))
    known = [
        RepairSQLColumnKnowledge(table="a0", column="Status", sample="1/19/2026", type="string"),
    ]
    asyncio.run(ai.intelligence_repair_sql_step(_req(known_columns=known)))
    prompt = captured["prompt"]
    assert "already requested" in prompt
    assert '"a0"."Status"' in prompt
    assert "1/19/2026" in prompt


def test_no_known_columns_omits_the_already_requested_block(monkeypatch):
    """The static instructions mention "already requested" in the abstract
    (telling the model not to re-request a column) even with no known columns
    -- what must NOT appear is an actual rendered column-detail line."""
    captured = _capture_generate(monkeypatch, json.dumps({"action": "give_up"}))
    asyncio.run(ai.intelligence_repair_sql_step(_req()))
    prompt = captured["prompt"]
    assert "example value=" not in prompt


def test_join_repair_keeps_join_rules(monkeypatch):
    join_sql = (
        'SELECT s."k" AS K, SUM(CAST(d."v" AS double)) AS V '
        'FROM "a0" s JOIN "b0" d ON s."k" = d."k" GROUP BY s."k"'
    )
    captured = _capture_generate(monkeypatch, json.dumps({"action": "give_up"}))
    asyncio.run(ai.intelligence_repair_sql_step(_req(sql=join_sql, allowed_tables=["a0", "b0"])))
    prompt = captured["prompt"]
    assert "KEEP the same two tables" in prompt
    assert "Do NOT write JOINs" not in prompt


def test_single_table_repair_uses_no_join_rule(monkeypatch):
    captured = _capture_generate(monkeypatch, json.dumps({"action": "give_up"}))
    asyncio.run(ai.intelligence_repair_sql_step(_req()))
    prompt = captured["prompt"]
    assert "Do NOT write JOINs" in prompt
    assert "KEEP the same two tables" not in prompt


def test_response_format_json_is_requested(monkeypatch):
    captured = _capture_generate(monkeypatch, json.dumps({"action": "give_up"}))
    asyncio.run(ai.intelligence_repair_sql_step(_req()))
    assert captured["response_format"] == "json"
