"""Tests for the SQL repair loop's fast-fail behavior on unfixable Teiid errors.

A production trace showed queries against dialect-incompatible functions
(DATEADD, DATE_FORMAT -- not Teiid functions) and malformed generated SQL
burning the full repair budget (multiple Teiid round trips plus repair-agent
calls) on every single request, since nothing told the loop these error
classes are not the kind an LLM rewrite reliably resolves.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.routes.query_sql_helpers import _execute_sql_with_repair
from app.services import ai_intelligence_client as aic

pytestmark = pytest.mark.anyio


class _FakeEndpoint:
    pg_host = "localhost"
    pg_port = 5433


async def _run_repair(
    monkeypatch, *, run_sql_error: str, rewrite_sql_at_call: list[str] | None = None
):
    run_sql_calls: list[str] = []
    repair_step_calls: list[str] = []

    async def fake_run_sql(**kwargs):
        run_sql_calls.append(kwargs["sql"])
        raise HTTPException(status_code=500, detail=run_sql_error)

    rewrites = iter(rewrite_sql_at_call or [])

    async def fake_repair_step(**kwargs):
        repair_step_calls.append(kwargs["sql"])
        try:
            sql = next(rewrites)
        except StopIteration:
            return {"action": "give_up", "sql": "", "table": "", "column": ""}
        return {"action": "rewrite", "sql": sql, "table": "", "column": ""}

    monkeypatch.setattr("app.routes.query_sql_helpers._run_sql", fake_run_sql)
    monkeypatch.setattr(aic, "repair_sql_step", fake_repair_step)

    result, _final_sql, _bounded_sql = await _execute_sql_with_repair(
        raw_sql="SELECT DATE_FORMAT(x, '%Y-%m') AS period FROM t",
        tenant_id=1,
        user_id=1,
        project_id=1,
        database="db",
        endpoint=_FakeEndpoint(),
        table_schema=[],
        allowed_tables=["t"],
        column_types={},
        column_samples={},
    )
    return result, run_sql_calls, repair_step_calls


@pytest.mark.parametrize(
    "error",
    [
        "TEIID30068 The function 'DATE_FORMAT(x, '%Y-%m')' is an unknown form.",
        "TEIID30328 Unable to evaluate FORMATTIMESTAMP(convert(A.RenewalMonth, timestamp), 'yyyy-MM')",
        "TEIID30384 Error while evaluating function convert",
        'TEIID31100 Parsing error: Encountered "*) AS value FROM \\"t\\"" at line 1, column 20.',
    ],
)
async def test_dialect_and_parse_errors_fail_fast_without_llm_repair(monkeypatch, error):
    result, run_sql_calls, repair_step_calls = await _run_repair(
        monkeypatch, run_sql_error=error
    )

    assert result is None
    # One Teiid round trip, not the full max_attempts budget -- and no
    # repair-agent call, since these error classes keep recurring unchanged.
    assert len(run_sql_calls) == 1
    assert repair_step_calls == []


async def test_other_errors_still_go_through_the_full_repair_loop(monkeypatch):
    result, run_sql_calls, repair_step_calls = await _run_repair(
        monkeypatch,
        run_sql_error="TEIID30999 some transient issue",
        # A genuinely different rewrite each time -- the loop stops early on
        # a rewrite identical to what it already tried, so returning the same
        # SQL twice would not exercise "goes through the full loop".
        rewrite_sql_at_call=["SELECT 1", "SELECT 2"],
    )

    assert result is None
    assert len(run_sql_calls) == 3
    assert len(repair_step_calls) == 2
