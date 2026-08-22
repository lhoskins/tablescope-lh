"""vLLM (observed with the muse-glimmer image's custom tool-call/reasoning
parser) intermittently drops the connection before writing any HTTP response
at all -- reproduced identically with a plain curl against the live host, so
this is a server-side drop, not something about how this client builds the
request. httpx surfaces that as a connection-level exception (ConnectError /
RemoteProtocolError / ReadError) rather than an HTTPStatusError.

_generate_openai now retries the connection itself a couple of times with a
short backoff before surfacing a hard failure, via _post_json_with_retry.
This must NOT retry a real HTTP error response (e.g. a 400 for a too-long
prompt) -- that's an actual answer from the server, not a dropped connection.

Run from ``tablescope-ai-api``:
``pytest -q tests/test_llm_client_connection_retry.py``.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.services import llm_client


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200, text: str = ""):
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{self.status_code} error", request=None, response=self  # type: ignore[arg-type]
            )

    def json(self) -> dict:
        return self._payload


def _chat_completion(message: dict) -> dict:
    return {"choices": [{"message": message}]}


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """The retry backoff (1s, 3s) would otherwise make every test in this
    file slow -- the delay itself isn't what's under test."""
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return slept


@pytest.fixture
def _patch_async_client(monkeypatch):
    """Unlike test_llm_client_openai_target.py's fixture, `post` here can be
    scripted to raise on early calls and only succeed on a later one, to
    exercise the retry path."""
    state: dict = {"responses": [], "calls": 0, "urls": []}

    class _FakeAsyncClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json):
            state["urls"].append(url)
            outcome = state["responses"][state["calls"]]
            state["calls"] += 1
            if isinstance(outcome, Exception):
                raise outcome
            return outcome if isinstance(outcome, _FakeResponse) else _FakeResponse(outcome)

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    return state


@pytest.mark.asyncio
async def test_connection_dropped_once_then_succeeds(_patch_async_client, _no_sleep):
    _patch_async_client["responses"] = [
        httpx.ConnectError("connection reset"),
        _chat_completion({"content": "ok"}),
    ]

    result = await llm_client._generate_openai(
        prompt="p", model="muse-glimmer", target_url="http://vllm/v1",
    )

    assert result == "ok"
    assert _patch_async_client["calls"] == 2
    assert _no_sleep == [1.0]  # only the first backoff delay was needed


@pytest.mark.asyncio
async def test_remote_protocol_error_is_retried(_patch_async_client, _no_sleep):
    """RemoteProtocolError ("Server disconnected without sending a
    response") is httpx's shape for exactly the observed 000/curl symptom."""
    _patch_async_client["responses"] = [
        httpx.RemoteProtocolError("Server disconnected without sending a response."),
        _chat_completion({"content": "ok"}),
    ]

    result = await llm_client._generate_openai(
        prompt="p", model="muse-glimmer", target_url="http://vllm/v1",
    )

    assert result == "ok"


@pytest.mark.asyncio
async def test_exhausting_all_retries_raises_the_last_connection_error(_patch_async_client, _no_sleep):
    _patch_async_client["responses"] = [
        httpx.ConnectError("drop 1"),
        httpx.ConnectError("drop 2"),
        httpx.ConnectError("drop 3"),
    ]

    with pytest.raises(httpx.ConnectError, match="drop 3"):
        await llm_client._generate_openai(
            prompt="p", model="muse-glimmer", target_url="http://vllm/v1",
        )

    assert _patch_async_client["calls"] == 3
    assert _no_sleep == [1.0, 3.0]  # both backoff delays were used


@pytest.mark.asyncio
async def test_a_real_http_error_response_is_not_retried(_patch_async_client, _no_sleep):
    """A 400 is a real answer from vLLM (e.g. a too-long prompt) -- it must
    surface immediately, not be treated as a dropped connection."""
    _patch_async_client["responses"] = [
        _FakeResponse({}, status_code=400, text="prompt too long"),
    ]

    with pytest.raises(httpx.HTTPStatusError):
        await llm_client._generate_openai(
            prompt="p", model="muse-glimmer", target_url="http://vllm/v1",
        )

    assert _patch_async_client["calls"] == 1
    assert _no_sleep == []
