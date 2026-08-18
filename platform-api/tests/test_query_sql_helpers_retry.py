"""``_run_sql``'s cold-VDB retry must cover Teiid's translator-capability-not-
loaded error, not just stale sessions (TEIID4004) and connection timeouts.

"Capabilities for X were not available" (TEIID30498/30492/30496) is what
Teiid raises when a query lands before ``vdb_warming.py``'s per-source
translator metadata load has finished -- the same cold-VDB condition, just
surfaced instead of prevented. Before this fix it fell through to an
immediate failure with zero retries, unlike every other cold-VDB symptom
this function already handles.

Run from ``platform-api``: ``pytest -q tests/test_query_sql_helpers_retry.py``.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.routes import query_sql_helpers as qsh


class _FakeConn:
    def __init__(self, calls: list[str], fail_times: int, exc: Exception):
        self._calls = calls
        self._fail_times = fail_times
        self._exc = exc

    async def fetch(self, sql: str):
        self._calls.append(sql)
        if len(self._calls) <= self._fail_times:
            raise self._exc
        return []


class _FakeAcquireCtx:
    def __init__(self, conn: _FakeConn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *a):
        return False


class _FakePool:
    def __init__(self, conn: _FakeConn):
        self._conn = conn

    def acquire(self):
        return _FakeAcquireCtx(self._conn)


def _patch_pool(monkeypatch, conn: _FakeConn, evictions: list[tuple]):
    async def fake_get_pool(**kwargs):
        return _FakePool(conn)

    async def fake_evict_pool(**kwargs):
        evictions.append(kwargs)

    monkeypatch.setattr(qsh.pool_manager, "get_pool", fake_get_pool)
    monkeypatch.setattr(qsh.pool_manager, "evict_pool", fake_evict_pool)


@pytest.mark.asyncio
async def test_run_sql_retries_on_cold_capabilities_error(monkeypatch):
    calls: list[str] = []
    evictions: list[tuple] = []
    exc = Exception("Capabilities for 'sales_revenue_monthly' were not available")
    conn = _FakeConn(calls, fail_times=1, exc=exc)
    _patch_pool(monkeypatch, conn, evictions)

    async def _fake_sleep(*_a, **_k):
        return None

    monkeypatch.setattr(qsh.asyncio, "sleep", _fake_sleep)

    result = await qsh._run_sql(database="db.1", sql="SELECT 1")

    assert result == {"columns": [], "rows": []}
    assert len(calls) == 2
    assert len(evictions) == 1


@pytest.mark.asyncio
async def test_run_sql_gives_up_after_two_cold_capabilities_failures(monkeypatch):
    calls: list[str] = []
    evictions: list[tuple] = []
    exc = Exception("Capabilities for 'sales_revenue_monthly' were not available")
    conn = _FakeConn(calls, fail_times=2, exc=exc)
    _patch_pool(monkeypatch, conn, evictions)

    async def _fake_sleep(*_a, **_k):
        return None

    monkeypatch.setattr(qsh.asyncio, "sleep", _fake_sleep)

    with pytest.raises(HTTPException):
        await qsh._run_sql(database="db.1", sql="SELECT 1")

    assert len(calls) == 2
    assert len(evictions) == 1


@pytest.mark.asyncio
async def test_run_sql_still_retries_stale_session(monkeypatch):
    calls: list[str] = []
    evictions: list[tuple] = []
    exc = Exception("TEIID40041 stale session")
    conn = _FakeConn(calls, fail_times=1, exc=exc)
    _patch_pool(monkeypatch, conn, evictions)

    result = await qsh._run_sql(database="db.1", sql="SELECT 1")

    assert result == {"columns": [], "rows": []}
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_run_sql_does_not_retry_unrelated_errors(monkeypatch):
    calls: list[str] = []
    evictions: list[tuple] = []
    exc = Exception("Group does not exist: foo")
    conn = _FakeConn(calls, fail_times=1, exc=exc)
    _patch_pool(monkeypatch, conn, evictions)

    with pytest.raises(HTTPException):
        await qsh._run_sql(database="db.1", sql="SELECT 1")

    assert len(calls) == 1
    assert len(evictions) == 0
