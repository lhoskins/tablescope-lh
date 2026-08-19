"""_generate_openai (the vLLM/OpenAI-compatible path) must not silently turn
an empty completion into guaranteed-unparseable input, and num_ctx must
actually influence the request instead of being dropped.

Root cause traced from a live "AI proposed 0" report on project 44: the
served model (a reasoning model, e.g. muse-glimmer) returns "reasoning" and
"content" as separate message fields. When content came back empty, `content
= message.get("content") or message.get("reasoning") or ""` handed the
reasoning trace -- a paraphrase of the prompt, not JSON -- to
_parse_json_response, which failed and looked like "malformed model output"
rather than what it actually was: no output. Separately, num_ctx (the
caller's context-size hint) was accepted by generate() but only ever
threaded through to the Ollama path; the OpenAI/vLLM path silently dropped
it, leaving it to the server's own default completion budget.

Run from ``tablescope-ai-api``:
``pytest -q tests/test_llm_client_openai_target.py``.
"""

from __future__ import annotations

import httpx
import pytest

from app.services import llm_client


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def _chat_completion(message: dict) -> dict:
    return {"choices": [{"message": message}]}


@pytest.fixture(autouse=True)
def _patch_async_client(monkeypatch):
    captured: dict = {}

    class _FakeAsyncClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json):
            captured["url"] = url
            captured["json"] = json
            return _FakeResponse(captured["response"])

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    return captured


@pytest.mark.asyncio
async def test_empty_content_does_not_fall_back_to_reasoning_trace(_patch_async_client):
    _patch_async_client["response"] = _chat_completion(
        {"content": "", "reasoning": "Let me think about the dashboard request..."}
    )

    result = await llm_client._generate_openai(
        prompt="p", model="muse-glimmer", target_url="http://vllm/v1",
    )

    assert result == ""


@pytest.mark.asyncio
async def test_real_content_is_returned_normally(_patch_async_client):
    _patch_async_client["response"] = _chat_completion(
        {"content": '{"suggestions": []}', "reasoning": "some internal trace"}
    )

    result = await llm_client._generate_openai(
        prompt="p", model="muse-glimmer", target_url="http://vllm/v1",
    )

    assert result == '{"suggestions": []}'


@pytest.mark.asyncio
async def test_missing_reasoning_field_still_falls_back_to_empty_string(_patch_async_client):
    _patch_async_client["response"] = _chat_completion({"content": None})

    result = await llm_client._generate_openai(
        prompt="p", model="muse-glimmer", target_url="http://vllm/v1",
    )

    assert result == ""


@pytest.mark.asyncio
async def test_num_ctx_becomes_a_max_tokens_reservation_for_vllm_targets(_patch_async_client):
    _patch_async_client["response"] = _chat_completion({"content": "{}"})

    await llm_client.generate(
        prompt="p",
        model="muse-glimmer",
        ollama_url="http://vllm/v1",
        num_ctx=24576,
        response_format="json",
    )

    assert _patch_async_client["json"]["max_tokens"] == 4096


@pytest.mark.asyncio
async def test_explicit_max_tokens_is_never_overridden_by_num_ctx(_patch_async_client):
    _patch_async_client["response"] = _chat_completion({"content": "SELECT 1"})

    await llm_client.generate(
        prompt="p",
        model="sql-model",
        ollama_url="http://vllm/v1",
        max_tokens=1024,
        num_ctx=24576,
    )

    assert _patch_async_client["json"]["max_tokens"] == 1024


@pytest.mark.asyncio
async def test_no_num_ctx_and_no_max_tokens_omits_max_tokens_entirely(_patch_async_client):
    _patch_async_client["response"] = _chat_completion({"content": "ok"})

    await llm_client.generate(
        prompt="p", model="muse-glimmer", ollama_url="http://vllm/v1",
    )

    assert "max_tokens" not in _patch_async_client["json"]
