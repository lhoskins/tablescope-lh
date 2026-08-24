"""_generate_openai (the vLLM/OpenAI-compatible path) must not silently turn
an empty completion into guaranteed-unparseable input, and must not risk
turning a large prompt into a hard 400 by guessing a max_tokens reservation
it cannot verify is safe.

Root cause of a live "AI proposed 0" report on project 44: the served model
(a reasoning model, e.g. muse-glimmer) returns "reasoning" and "content" as
separate message fields. When content came back empty, `content =
message.get("content") or message.get("reasoning") or ""` handed the
reasoning trace -- a paraphrase of the prompt, not JSON -- to
_parse_json_response, which failed and looked like "malformed model output"
rather than what it actually was: no output.

A first fix translated the caller's num_ctx hint into an explicit max_tokens
reservation for this path (since num_ctx itself has no vLLM equivalent).
That regressed project 44 from a soft failure to a hard one: ai-server has
no tokenizer, so it doesn't know the real prompt token count, and vLLM
rejects prompt_tokens + max_tokens > max_model_len with a 400 rather than
truncating. Confirmed live: project 44's prompt is >= 8193 tokens against a
12288 max_model_len, so a 4096-token reservation always overflowed it. Fixed
by leaving max_tokens unset here when the caller didn't supply one --
letting vLLM size the completion itself from the prompt it just tokenized,
which is strictly safer than any client-side guess.

Also covers that a 400 (or other HTTP error) from vLLM now logs the response
body before re-raising -- raise_for_status() alone discards it, which is why
the max_tokens regression above first surfaced as a bare, unexplained 400.

Run from ``tablescope-ai-api``:
``pytest -q tests/test_llm_client_openai_target.py``.
"""

from __future__ import annotations

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
            response = captured["response"]
            return response if isinstance(response, _FakeResponse) else _FakeResponse(response)

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
async def test_empty_content_warning_logs_finish_reason_and_budget(_patch_async_client, caplog):
    """finish_reason distinguishes a token-budget problem (fixable client-side)
    from the model choosing to stop after reasoning (a model/prompt-serving
    problem) -- without it, every empty-content report looks the same and a
    root cause can't be told apart from a guess."""
    _patch_async_client["response"] = _chat_completion(
        {"content": "", "reasoning": "short trace"}
    )
    _patch_async_client["response"]["choices"][0]["finish_reason"] = "stop"

    with caplog.at_level("WARNING"):
        await llm_client._generate_openai(
            prompt="p", model="muse-glimmer", target_url="http://vllm/v1",
            max_tokens=400,
        )

    assert any(
        "finish_reason=stop" in record.message and "max_tokens=400" in record.message
        for record in caplog.records
    )


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
async def test_num_ctx_has_no_effect_on_vllm_targets(_patch_async_client):
    """num_ctx has no vLLM equivalent and must never be turned into a guessed
    max_tokens -- ai-server has no tokenizer, so it cannot know whether a
    reservation is safe against the real prompt token count. A large num_ctx
    hint (as dashboard-suggest passes) must leave max_tokens unset, letting
    vLLM size the completion itself instead of risking a 400."""
    _patch_async_client["response"] = _chat_completion({"content": "{}"})

    await llm_client.generate(
        prompt="p",
        model="muse-glimmer",
        ollama_url="http://vllm/v1",
        num_ctx=24576,
        response_format="json",
    )

    assert "max_tokens" not in _patch_async_client["json"]


@pytest.mark.asyncio
async def test_explicit_max_tokens_is_passed_through_unchanged(_patch_async_client):
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
async def test_generate_omits_min_tokens_when_unset(_patch_async_client):
    """A plain generate() call is unaffected by the SQL-path fix below --
    min_tokens must stay opt-in, not a blanket default for every caller."""
    _patch_async_client["response"] = _chat_completion({"content": "hi"})

    await llm_client.generate(prompt="p", model="m", ollama_url="http://vllm/v1")

    assert "min_tokens" not in _patch_async_client["json"]


@pytest.mark.asyncio
async def test_generate_sql_sends_min_tokens(_patch_async_client):
    """Reproduces the live fix: generate_sql must set min_tokens so vLLM
    can't stop after a short reasoning-only burst, well under max_tokens,
    before ever reaching the SQL answer (confirmed live -- see llm_client's
    _SQL_MIN_TOKENS comment)."""
    _patch_async_client["response"] = _chat_completion({"content": "SELECT 1"})

    await llm_client.generate_sql(
        prompt="revenue by quarter",
        context="",
        allowed_tables=["sales_revenue_monthly_CSV"],
        model="sql-model",
        ollama_url="http://vllm/v1",
    )

    assert _patch_async_client["json"]["min_tokens"] == llm_client._SQL_MIN_TOKENS


@pytest.mark.asyncio
async def test_repair_sql_sends_min_tokens(_patch_async_client):
    _patch_async_client["response"] = _chat_completion({"content": "SELECT 1"})

    await llm_client.repair_sql(
        prompt="revenue by quarter",
        context="",
        allowed_tables=["sales_revenue_monthly_CSV"],
        failed_sql="SELECT 1",
        validation_error="TEIID30492",
        model="sql-model",
        ollama_url="http://vllm/v1",
    )

    assert _patch_async_client["json"]["min_tokens"] == llm_client._SQL_MIN_TOKENS


@pytest.mark.asyncio
async def test_no_num_ctx_and_no_max_tokens_omits_max_tokens_entirely(_patch_async_client):
    _patch_async_client["response"] = _chat_completion({"content": "ok"})

    await llm_client.generate(
        prompt="p", model="muse-glimmer", ollama_url="http://vllm/v1",
    )

    assert "max_tokens" not in _patch_async_client["json"]


@pytest.mark.asyncio
async def test_http_error_logs_the_response_body_before_reraising(_patch_async_client, caplog):
    """raise_for_status() alone discards the response body -- this is the
    exact failure mode from the live regression: a bare, unexplained 400 with
    no clue in the logs that vLLM's real complaint was a token-budget
    overflow."""
    _patch_async_client["response"] = _FakeResponse(
        {},
        status_code=400,
        text=(
            "This model's maximum context length is 12288 tokens. However, "
            "you requested 4096 output tokens and your prompt contains at "
            "least 8193 input tokens, for a total of at least 12289 tokens."
        ),
    )

    with caplog.at_level("ERROR"):
        with pytest.raises(httpx.HTTPStatusError):
            await llm_client._generate_openai(
                prompt="p", model="muse-glimmer", target_url="http://vllm/v1",
            )

    assert "maximum context length is 12288" in caplog.text
