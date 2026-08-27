"""Unit tests for the shared SQL self-repair agent loop.

Exercises app.services.sql_repair_agent.run_repair_loop directly with fake
normalize/execute callbacks, isolated from any particular caller (chat
ask-and-run, saved-query execution) -- those callers' own integration tests
(test_ai_ask_and_run.py, test_query_sql_repair.py) cover their specific
wiring; this covers the shared loop mechanics itself: execute-attempt and
repair-step bounds, the inspect_column/rewrite/give_up action handling, and
the AI-unavailable degrade path.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.services import ai_intelligence_client as aic
from app.services.sql_repair_agent import (
    _MAX_EXECUTE_ATTEMPTS,
    _MAX_REPAIR_STEPS,
    is_read_only_select,
    run_repair_loop,
)

pytestmark = pytest.mark.anyio


async def _normalize(sql: str) -> str:
    return sql


def _fail(sql: str) -> None:
    raise HTTPException(status_code=502, detail="TEIID30068 unknown function")


async def _run(
    monkeypatch,
    *,
    execute,
    decisions=None,
    normalize=_normalize,
    is_unfixable_error=None,
    max_execute_attempts: int = _MAX_EXECUTE_ATTEMPTS,
    max_repair_steps: int = _MAX_REPAIR_STEPS,
):
    calls: list[dict] = []
    decisions_iter = iter(decisions or [])

    async def fake_repair_step(**kwargs):
        calls.append(kwargs)
        try:
            return next(decisions_iter)
        except StopIteration:
            return {"action": "give_up", "sql": "", "table": "", "column": ""}

    monkeypatch.setattr(aic, "repair_sql_step", fake_repair_step)

    result = await run_repair_loop(
        initial_sql="SELECT DATEDIFF(a, b) FROM t",
        tenant_id=1,
        user_id=1,
        project_id=1,
        allowed_tables=["t"],
        table_schema=[{"table": "t", "columns": [{"name": "a", "type": "string"}]}],
        column_samples={"a": "1/19/2026"},
        column_types={"a": "string"},
        normalize=normalize,
        execute=execute,
        is_unfixable_error=is_unfixable_error,
        max_execute_attempts=max_execute_attempts,
        max_repair_steps=max_repair_steps,
    )
    return result, calls


async def test_succeeds_immediately_without_calling_the_agent(monkeypatch):
    async def execute(sql: str) -> dict:
        return {"columns": ["x"], "rows": [{"x": 1}]}

    (result, _sql, error), calls = await _run(monkeypatch, execute=execute)
    assert result == {"columns": ["x"], "rows": [{"x": 1}]}
    assert error == ""
    assert calls == []


async def test_rewrite_action_is_applied_and_retried(monkeypatch):
    attempts: list[str] = []

    async def execute(sql: str) -> dict:
        attempts.append(sql)
        if "DATEDIFF" in sql:
            _fail(sql)
        return {"columns": ["x"], "rows": [{"x": 5}]}

    good = "SELECT TIMESTAMPDIFF(SQL_TSI_DAY, a, b) FROM t"
    (result, final_sql, error), calls = await _run(
        monkeypatch,
        execute=execute,
        decisions=[{"action": "rewrite", "sql": good, "table": "", "column": ""}],
    )
    assert result == {"columns": ["x"], "rows": [{"x": 5}]}
    assert final_sql == good
    assert error == ""
    assert len(attempts) == 2
    assert len(calls) == 1


async def test_inspect_column_reveals_sample_then_rewrite_succeeds(monkeypatch):
    async def execute(sql: str) -> dict:
        if "DATEDIFF" in sql:
            _fail(sql)
        return {"columns": ["x"], "rows": [{"x": 5}]}

    good = "SELECT TIMESTAMPDIFF(SQL_TSI_DAY, a, b) FROM t"
    (result, final_sql, _error), calls = await _run(
        monkeypatch,
        execute=execute,
        decisions=[
            {"action": "inspect_column", "sql": "", "table": "t", "column": "a"},
            {"action": "rewrite", "sql": good, "table": "", "column": ""},
        ],
    )
    assert result is not None
    assert final_sql == good
    assert len(calls) == 2
    assert calls[0]["known_columns"] == []
    assert calls[1]["known_columns"] == [
        {"column": "a", "table": "t", "sample": "1/19/2026", "type": "string"}
    ]


async def test_give_up_returns_none_with_last_error(monkeypatch):
    async def execute(sql: str) -> dict:
        _fail(sql)

    (result, _final_sql, error), calls = await _run(
        monkeypatch,
        execute=execute,
        decisions=[{"action": "give_up", "sql": "", "table": "", "column": ""}],
    )
    assert result is None
    assert "TEIID30068" in error
    assert len(calls) == 1


async def test_repeated_inspect_column_request_stops_the_loop(monkeypatch):
    async def execute(sql: str) -> dict:
        _fail(sql)

    (result, _final_sql, _error), calls = await _run(
        monkeypatch,
        execute=execute,
        decisions=[
            {"action": "inspect_column", "sql": "", "table": "t", "column": "a"},
            {"action": "inspect_column", "sql": "", "table": "t", "column": "a"},
        ],
    )
    assert result is None
    assert len(calls) == 2


async def test_bounded_by_max_repair_steps(monkeypatch):
    async def execute(sql: str) -> dict:
        _fail(sql)

    async def fake_repair_step(**kwargs):
        n = len(calls_seen)
        calls_seen.append(1)
        return {"action": "inspect_column", "sql": "", "table": "t", "column": f"col{n}"}

    calls_seen: list[int] = []
    monkeypatch.setattr(aic, "repair_sql_step", fake_repair_step)

    result = await run_repair_loop(
        initial_sql="SELECT DATEDIFF(a, b) FROM t",
        tenant_id=1,
        user_id=1,
        project_id=1,
        allowed_tables=["t"],
        table_schema=[],
        column_samples={},
        column_types={},
        normalize=_normalize,
        execute=execute,
        max_repair_steps=3,
    )
    assert result[0] is None
    assert len(calls_seen) == 3


async def test_bounded_by_max_execute_attempts(monkeypatch):
    executes: list[str] = []

    async def execute(sql: str) -> dict:
        executes.append(sql)
        _fail(sql)

    (result, _final_sql, _error), _calls = await _run(
        monkeypatch,
        execute=execute,
        decisions=[
            {"action": "rewrite", "sql": "SELECT 1 FROM t", "table": "", "column": ""},
            {"action": "rewrite", "sql": "SELECT 2 FROM t", "table": "", "column": ""},
        ],
        max_execute_attempts=2,
    )
    assert result is None
    assert len(executes) == 2


async def test_ai_unavailable_degrades_to_give_up(monkeypatch):
    async def execute(sql: str) -> dict:
        _fail(sql)

    async def fake_repair_step(**kwargs):
        raise aic.AIUnavailableError("down")

    monkeypatch.setattr(aic, "repair_sql_step", fake_repair_step)

    result = await run_repair_loop(
        initial_sql="SELECT DATEDIFF(a, b) FROM t",
        tenant_id=1,
        user_id=1,
        project_id=1,
        allowed_tables=["t"],
        table_schema=[],
        column_samples={},
        column_types={},
        normalize=_normalize,
        execute=execute,
    )
    assert result[0] is None
    assert "TEIID30068" in result[2]


async def test_unfixable_error_skips_the_agent_entirely(monkeypatch):
    async def execute(sql: str) -> dict:
        raise HTTPException(status_code=502, detail="Table foo does not exist")

    async def fail_if_called(**kwargs):
        raise AssertionError("repair_sql_step must not be called for an unfixable error")

    monkeypatch.setattr(aic, "repair_sql_step", fail_if_called)

    result = await run_repair_loop(
        initial_sql="SELECT 1 FROM t",
        tenant_id=1,
        user_id=1,
        project_id=1,
        allowed_tables=["t"],
        table_schema=[],
        column_samples={},
        column_types={},
        normalize=_normalize,
        execute=execute,
        is_unfixable_error=lambda err: "does not exist" in err,
    )
    assert result[0] is None
    assert "does not exist" in result[2]


async def test_rewrite_identical_to_current_sql_stops_the_loop(monkeypatch):
    same = "SELECT DATEDIFF(a, b) FROM t"

    async def execute(sql: str) -> dict:
        _fail(sql)

    (result, _final_sql, _error), calls = await _run(
        monkeypatch,
        execute=execute,
        decisions=[{"action": "rewrite", "sql": same, "table": "", "column": ""}],
    )
    assert result is None
    assert len(calls) == 1


async def test_rewrite_that_is_not_read_only_select_is_rejected(monkeypatch):
    async def execute(sql: str) -> dict:
        _fail(sql)

    (result, _final_sql, _error), _calls = await _run(
        monkeypatch,
        execute=execute,
        decisions=[
            {"action": "rewrite", "sql": "DELETE FROM t", "table": "", "column": ""}
        ],
    )
    assert result is None


def test_is_read_only_select() -> None:
    assert is_read_only_select("SELECT a FROM t")
    assert is_read_only_select("  with cte as (select 1) select * from cte")
    assert is_read_only_select("-- note\nSELECT a FROM t")
    assert not is_read_only_select("To calculate the rate, SELECT a FROM t")
    assert not is_read_only_select("DELETE FROM t")
    assert not is_read_only_select("")
