"""TS-ISO-011: platform-api client for the new signed vector-deletion routes.

``delete_tenant_collection``/``delete_project_vectors`` are called
best-effort from the tenant/project deletion routes -- they must return
``False`` (nothing to do) when the AI server is disabled, ``True`` on a
successful call, and raise ``AIUnavailableError`` on a genuine failure so
the caller can log it instead of mistaking a real outage for "nothing to
delete."
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

import app.services.ai_intelligence_client as aic


@pytest.fixture
def ai_enabled(monkeypatch):
    monkeypatch.setattr(
        aic,
        "get_settings",
        lambda: SimpleNamespace(
            tablescope_ai_enabled=True,
            tablescope_ai_api_url="http://ai",
            tablescope_ai_signing_secret="secret",
        ),
    )
    monkeypatch.setattr(aic, "is_enabled", lambda: True)
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())


@pytest.fixture
def ai_disabled(monkeypatch):
    monkeypatch.setattr(
        aic,
        "get_settings",
        lambda: SimpleNamespace(
            tablescope_ai_enabled=False,
            tablescope_ai_api_url="",
            tablescope_ai_signing_secret="secret",
        ),
    )
    monkeypatch.setattr(aic, "is_enabled", lambda: False)


async def test_delete_tenant_collection_returns_false_when_ai_disabled(ai_disabled):
    result = await aic.delete_tenant_collection(tenant_id=1)
    assert result is False


async def test_delete_tenant_collection_returns_true_on_success(ai_enabled, monkeypatch):
    captured = {}

    async def fake_post(self, url, content, **kwargs):
        import json

        captured["url"] = url
        captured["body"] = json.loads(content)
        return httpx.Response(200, json={"status": "ok"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    result = await aic.delete_tenant_collection(tenant_id=42)

    assert result is True
    assert captured["url"] == "http://ai/vector-store/delete-tenant-collection"
    assert captured["body"]["tenant_id"] == 42


async def test_delete_tenant_collection_raises_on_server_error(ai_enabled, monkeypatch):
    async def fake_post(self, url, **kwargs):
        return httpx.Response(500, json={"detail": "boom"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    with pytest.raises(aic.AIUnavailableError):
        await aic.delete_tenant_collection(tenant_id=1)


async def test_delete_project_vectors_returns_false_when_ai_disabled(ai_disabled):
    result = await aic.delete_project_vectors(tenant_id=1, project_id=10)
    assert result is False


async def test_delete_project_vectors_returns_true_on_success(ai_enabled, monkeypatch):
    captured = {}

    async def fake_post(self, url, content, **kwargs):
        import json

        captured["url"] = url
        captured["body"] = json.loads(content)
        return httpx.Response(200, json={"status": "ok"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    result = await aic.delete_project_vectors(tenant_id=1, project_id=10)

    assert result is True
    assert captured["url"] == "http://ai/vector-store/delete-project-vectors"
    assert captured["body"]["tenant_id"] == 1
    assert captured["body"]["project_id"] == 10


async def test_delete_project_vectors_raises_on_server_error(ai_enabled, monkeypatch):
    async def fake_post(self, url, **kwargs):
        return httpx.Response(500, json={"detail": "boom"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    with pytest.raises(aic.AIUnavailableError):
        await aic.delete_project_vectors(tenant_id=1, project_id=10)
