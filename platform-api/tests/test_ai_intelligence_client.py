from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from app.services import ai_intelligence_client as client


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        tablescope_ai_api_url="http://ai-server",
        tablescope_ai_signing_secret="secret",
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


async def test_post_treats_ai_server_busy_as_unavailable(monkeypatch) -> None:
    class BusyClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def post(self, *_args, **_kwargs) -> httpx.Response:
            return httpx.Response(
                503,
                request=httpx.Request(
                    "POST", "http://ai-server/ai/intelligence/interpret"
                ),
                json={"detail": "AI server is busy; retry shortly."},
            )

    monkeypatch.setattr(client, "is_enabled", lambda: True)
    monkeypatch.setattr(client, "get_settings", _settings)
    monkeypatch.setattr(client.httpx, "AsyncClient", BusyClient)

    with pytest.raises(client.AIUnavailableError, match="busy") as captured:
        await client._post("/ai/intelligence/interpret", {"tenant_id": 1})
    assert captured.value.status_code == 503


async def test_post_keeps_disabled_ai_as_clean_none(monkeypatch) -> None:
    monkeypatch.setattr(client, "is_enabled", lambda: False)
    monkeypatch.setattr(client, "get_settings", _settings)

    assert await client._post("/ai/intelligence/plan", {}) is None
