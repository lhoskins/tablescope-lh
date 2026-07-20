"""Tests for the retry-aware AI intelligence client."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

import app.services.ai_intelligence_client as aic


@pytest.fixture
def ai_enabled(monkeypatch):
    """Enable AI calls and point them at a fake base URL."""
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


async def test_generate_sql_retries_503_then_succeeds(ai_enabled, monkeypatch):
    """Transient 503s from the AI server are retried before succeeding."""
    call_count = 0

    async def fake_post(self, url, **kwargs):
        nonlocal call_count
        call_count += 1
        request = httpx.Request("POST", url)
        if call_count < 3:
            return httpx.Response(503, request=request)
        return httpx.Response(200, json={"sql": "SELECT 1", "explanation": ""}, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    result = await aic.generate_sql(
        tenant_id=1,
        user_id=1,
        project_id=1,
        prompt="test",
        allowed_tables=["t"],
    )
    assert call_count == 3
    assert result is not None
    assert result["sql"] == "SELECT 1"


async def test_ask_retries_503_then_succeeds(ai_enabled, monkeypatch):
    """Transient 503s on the prose endpoint are retried before succeeding."""
    call_count = 0

    async def fake_post(self, url, **kwargs):
        nonlocal call_count
        call_count += 1
        request = httpx.Request("POST", url)
        if call_count == 1:
            return httpx.Response(503, request=request)
        return httpx.Response(200, json={"answer": "Retry worked."}, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    result = await aic.ask(
        tenant_id=1,
        user_id=1,
        project_id=1,
        question="test",
    )
    assert call_count == 2
    assert result is not None
    assert result["answer"] == "Retry worked."
