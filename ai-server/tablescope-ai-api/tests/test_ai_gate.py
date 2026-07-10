from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

import pytest

from app.services.ai_gate import AIGate, AIGateBusyError


def test_gate_enforces_per_tenant_cap_without_blocking_other_tenants() -> None:
    async def run() -> None:
        gate = AIGate(
            global_limit=2,
            tenant_limit=1,
            acquire_timeout_seconds=1.0,
        )
        entered: list[str] = []
        entered_events = {
            "tenant-1-first": asyncio.Event(),
            "tenant-1-second": asyncio.Event(),
            "tenant-2": asyncio.Event(),
        }
        release = asyncio.Event()

        async def worker(name: str, tenant_id: int) -> None:
            async with gate.acquire(tenant_id):
                entered.append(name)
                entered_events[name].set()
                await release.wait()

        first = asyncio.create_task(worker("tenant-1-first", 1))
        await asyncio.wait_for(entered_events["tenant-1-first"].wait(), timeout=1)
        same_tenant = asyncio.create_task(worker("tenant-1-second", 1))
        other_tenant = asyncio.create_task(worker("tenant-2", 2))
        await asyncio.wait_for(entered_events["tenant-2"].wait(), timeout=1)

        assert "tenant-1-second" not in entered
        release.set()
        await asyncio.gather(first, same_tenant, other_tenant)
        assert "tenant-1-second" in entered

    asyncio.run(run())


def test_gate_enforces_global_cap_across_tenants() -> None:
    async def run() -> None:
        gate = AIGate(
            global_limit=1,
            tenant_limit=2,
            acquire_timeout_seconds=1.0,
        )
        first_entered = asyncio.Event()
        release = asyncio.Event()
        second_entered = False

        async def first() -> None:
            async with gate.acquire(1):
                first_entered.set()
                await release.wait()

        async def second() -> None:
            nonlocal second_entered
            async with gate.acquire(2):
                second_entered = True

        first_task = asyncio.create_task(first())
        await first_entered.wait()
        second_task = asyncio.create_task(second())
        await asyncio.sleep(0.01)
        assert second_entered is False
        release.set()
        await asyncio.gather(first_task, second_task)
        assert second_entered is True

    asyncio.run(run())


def test_eleven_same_tenant_requests_drain_with_tuned_limits() -> None:
    async def run() -> None:
        gate = AIGate(
            global_limit=4,
            tenant_limit=3,
            acquire_timeout_seconds=1.0,
        )
        active = 0
        max_active = 0
        completed: list[int] = []

        async def worker(index: int) -> None:
            nonlocal active, max_active
            async with gate.acquire(1):
                active += 1
                max_active = max(max_active, active)
                await asyncio.sleep(0.01)
                completed.append(index)
                active -= 1

        await asyncio.gather(*(worker(index) for index in range(11)))

        assert len(completed) == 11
        assert max_active == 3

    asyncio.run(run())


def test_gate_timeout_maps_to_http_503() -> None:
    async def run() -> None:
        from app.main import ai_gate_busy_handler

        gate = AIGate(
            global_limit=1,
            tenant_limit=1,
            acquire_timeout_seconds=0.01,
        )
        async with gate.acquire(1):
            with pytest.raises(AIGateBusyError) as captured:
                async with gate.acquire(1):
                    pass

        response = await ai_gate_busy_handler(None, captured.value)  # type: ignore[arg-type]
        assert response.status_code == 503
        assert response.headers["retry-after"] == "5"
        assert json.loads(response.body)["code"] == "ai_busy"

    asyncio.run(run())


def test_generate_without_tenant_uses_global_gate(monkeypatch) -> None:
    from app.services import llm_client

    acquired: list[int | None] = []

    @asynccontextmanager
    async def fake_acquire(tenant_id: int | None):
        acquired.append(tenant_id)
        yield

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"response": "ok"}

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def post(self, *_args, **_kwargs) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr(llm_client.ai_gate, "acquire", fake_acquire)
    monkeypatch.setattr(llm_client.httpx, "AsyncClient", FakeClient)

    assert asyncio.run(llm_client.generate("hello")) == "ok"
    assert acquired == [None]
