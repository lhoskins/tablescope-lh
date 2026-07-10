from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from app.services import ai_intelligence_client as client


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        tablescope_ai_api_url="http://ai-server",
        tablescope_ai_signing_secret="secret",
        home_intelligence_plan_max_retries=2,
        home_intelligence_plan_retry_base_seconds=0.5,
    )


async def test_post_raises_ai_unavailable_on_timeout(monkeypatch) -> None:
    class TimeoutClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def post(self, *_args, **_kwargs):
            raise httpx.ReadTimeout(
                "timed out",
                request=httpx.Request("POST", "http://ai-server/ai/intelligence/plan"),
            )

    monkeypatch.setattr(client, "is_enabled", lambda: True)
    monkeypatch.setattr(client, "get_settings", _settings)
    monkeypatch.setattr(client.httpx, "AsyncClient", TimeoutClient)

    with pytest.raises(client.AIUnavailableError, match="timed out"):
        await client._post("/ai/intelligence/plan", {"tenant_id": 1})


async def test_plan_retries_read_timeout_and_eventually_succeeds(monkeypatch) -> None:
    attempts = 0
    sleeps: list[float] = []

    class RecoveringClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def post(self, *_args, **_kwargs) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            request = httpx.Request(
                "POST", "http://ai-server/ai/intelligence/plan"
            )
            if attempts == 1:
                raise httpx.ReadTimeout("timed out", request=request)
            return httpx.Response(
                200,
                request=request,
                json={"analyses": [{"id": "a1"}]},
            )

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(client, "is_enabled", lambda: True)
    monkeypatch.setattr(client, "get_settings", _settings)
    monkeypatch.setattr(client.httpx, "AsyncClient", RecoveringClient)
    monkeypatch.setattr(client.asyncio, "sleep", fake_sleep)

    result = await client.plan(
        tenant_id=1,
        user_id=1,
        project_id=1,
        allowed_tables=[],
        documents=[],
    )

    assert result == [{"id": "a1"}]
    assert attempts == 2
    assert sleeps == [0.5]


async def test_post_treats_ai_server_busy_as_unavailable_after_retries(
    monkeypatch,
) -> None:
    attempts = 0
    sleeps: list[float] = []

    class BusyClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def post(self, *_args, **_kwargs) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(
                503,
                request=httpx.Request(
                    "POST", "http://ai-server/ai/intelligence/interpret"
                ),
                headers={"Retry-After": "2.5"},
                json={"detail": "AI server is busy; retry shortly."},
            )

    monkeypatch.setattr(client, "is_enabled", lambda: True)
    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(client, "get_settings", _settings)
    monkeypatch.setattr(client.httpx, "AsyncClient", BusyClient)
    monkeypatch.setattr(client.asyncio, "sleep", fake_sleep)

    with pytest.raises(client.AIUnavailableError, match="busy") as captured:
        await client._post("/ai/intelligence/interpret", {"tenant_id": 1})
    assert captured.value.status_code == 503
    assert attempts == 3
    assert sleeps == [2.5, 2.5]


async def test_post_retries_busy_response_and_eventually_succeeds(monkeypatch) -> None:
    attempts = 0
    sleeps: list[float] = []

    class RecoveringClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def post(self, *_args, **_kwargs) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            request = httpx.Request(
                "POST", "http://ai-server/ai/intelligence/interpret"
            )
            if attempts < 3:
                return httpx.Response(
                    503,
                    request=request,
                    headers={"Retry-After": "0.25"},
                )
            return httpx.Response(200, request=request, json={"insights": {}})

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(client, "is_enabled", lambda: True)
    monkeypatch.setattr(client, "get_settings", _settings)
    monkeypatch.setattr(client.httpx, "AsyncClient", RecoveringClient)
    monkeypatch.setattr(client.asyncio, "sleep", fake_sleep)

    result = await client._post("/ai/intelligence/interpret", {"tenant_id": 1})

    assert result == {"insights": {}}
    assert attempts == 3
    assert sleeps == [0.25, 0.25]


async def test_post_keeps_disabled_ai_as_clean_none(monkeypatch) -> None:
    monkeypatch.setattr(client, "is_enabled", lambda: False)
    monkeypatch.setattr(client, "get_settings", _settings)

    assert await client._post("/ai/intelligence/plan", {}) is None
