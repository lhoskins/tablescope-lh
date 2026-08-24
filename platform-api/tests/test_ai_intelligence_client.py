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


async def test_generate_sql_422_raises_declined_error_with_unwrapped_detail(
    ai_enabled, monkeypatch
):
    """A 4xx means the AI server was reached and responded -- it just
    rejected this specific request. That must be distinguishable from a
    genuine outage (declined=True), and FastAPI's {"detail": ...} envelope
    around the AI server's structured rejection must be unwrapped so callers
    see the same {"code", "message", "reason", "suggested_sources"} shape
    the AI server sent, not the envelope itself."""

    async def fake_post(self, url, **kwargs):
        request = httpx.Request("POST", url)
        return httpx.Response(
            422,
            json={
                "detail": {
                    "code": "needs_clarification",
                    "message": "Model did not return a runnable SQL query.",
                    "reason": "empty completion",
                    "suggested_sources": [],
                }
            },
            request=request,
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    with pytest.raises(aic.AIUnavailableError) as excinfo:
        await aic.generate_sql(
            tenant_id=1, user_id=1, project_id=1, prompt="test", allowed_tables=["t"]
        )
    exc = excinfo.value
    assert exc.status_code == 422
    assert exc.declined is True
    assert exc.detail == {
        "code": "needs_clarification",
        "message": "Model did not return a runnable SQL query.",
        "reason": "empty completion",
        "suggested_sources": [],
    }


async def test_generate_sql_503_is_not_declined(ai_enabled, monkeypatch):
    """A busy 503 (after exhausting retries) is a real availability signal,
    not the AI server declining the request -- declined must stay False so
    it keeps the hard "unavailable" treatment instead of a friendly one."""

    async def fake_post(self, url, **kwargs):
        request = httpx.Request("POST", url)
        return httpx.Response(503, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    with pytest.raises(aic.AIUnavailableError) as excinfo:
        await aic.generate_sql(
            tenant_id=1, user_id=1, project_id=1, prompt="test", allowed_tables=["t"]
        )
    assert excinfo.value.declined is False


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
