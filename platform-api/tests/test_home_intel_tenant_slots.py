"""Tests for the per-tenant fairness-token TTL self-heal.

A rejected (over-cap) acquire attempt must not refresh the slot key's TTL.
Refreshing it there too lets a leaked/stuck counter be kept alive forever by
the very retries it is blocking, defeating the TTL-based self-heal.
"""

from __future__ import annotations

import pytest

from app.services import home_intel_queue as q

pytestmark = pytest.mark.anyio


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.expire_calls: list[tuple[str, int]] = []

    async def incr(self, key: str) -> int:
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    async def decr(self, key: str) -> int:
        self.values[key] = self.values.get(key, 0) - 1
        return self.values[key]

    async def expire(self, key: str, ttl: int) -> None:
        self.expire_calls.append((key, ttl))

    async def set(self, key: str, value: int) -> None:
        self.values[key] = value


async def test_rejected_acquire_does_not_refresh_ttl(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(q, "get_redis", lambda: fake)

    # Simulate a leaked slot: the counter is already at cap (e.g. a worker
    # crashed mid-analysis without releasing).
    fake.values[q._tenant_slots_key(1)] = 1

    acquired = await q.acquire_tenant_slot(1, cap=1)

    assert acquired is False
    assert fake.expire_calls == []
    # The rejected attempt must not leave the counter incremented.
    assert fake.values[q._tenant_slots_key(1)] == 1


async def test_successful_acquire_refreshes_ttl(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(q, "get_redis", lambda: fake)

    acquired = await q.acquire_tenant_slot(1, cap=2)

    assert acquired is True
    assert fake.expire_calls == [
        (q._tenant_slots_key(1), q._TENANT_SLOT_TTL_SECONDS)
    ]


async def test_retry_storm_against_leaked_slot_never_refreshes_ttl(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(q, "get_redis", lambda: fake)
    fake.values[q._tenant_slots_key(7)] = 1

    for _ in range(50):
        assert await q.acquire_tenant_slot(7, cap=1) is False

    assert fake.expire_calls == []
