"""_SEMANTIC_RULES must tell the model what to do when a source has NO
'profile' line, not just what to do when one is present.

Live incident: "What is the backup failure rate?" against `it_backup_jobs_CSV`
generated syntactically valid SQL (the TEIID31100/TEIID30492 defects fixed
elsewhere were both already gone) but returned zero rows. Root cause: the
source has no persisted `DataSourceAIProfile` (predates upload-time
profiling, per `data_source_profiler.py`'s own docstring), so no "profile"
line reaches the catalog -- and the existing semantic rule only tells the
model what to do when a profile line IS present ("check that range..."). With
no profile line, the model had no instruction against guessing a wall-clock
relative filter ("last 60 days"), and the actual data (June 2026) fell
outside that guessed window -- so every row was filtered out, not because the
question was unanswerable.

Run from ``tablescope-ai-api``:
``pytest -q tests/test_semantic_rules_no_profile_guidance.py``.
"""

from __future__ import annotations

import httpx
import pytest

from app.services import llm_client


def test_semantic_rules_cover_the_no_profile_case():
    rules = llm_client._SEMANTIC_RULES.lower()
    assert "no 'profile' line" in rules or "no \"profile\" line" in rules
    assert "relative" in rules
    assert "zero rows" in rules


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


@pytest.fixture
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
            captured["json"] = json
            return _FakeResponse({"choices": [{"message": {"content": "SELECT 1"}}]})

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    return captured


@pytest.mark.asyncio
async def test_generate_sql_prompt_includes_no_profile_guidance(_patch_async_client):
    """End-to-end: the no-profile rule actually reaches the system prompt
    generate_sql sends, not just the standalone _SEMANTIC_RULES constant."""
    await llm_client.generate_sql(
        prompt="What is the backup failure rate?",
        context="",
        allowed_tables=["it_backup_jobs_CSV"],
        llm_target_url="http://vllm/v1",
    )

    system_message = next(
        m["content"]
        for m in _patch_async_client["json"]["messages"]
        if m["role"] == "system"
    ).lower()
    assert "no 'profile' line" in system_message
    assert "zero rows" in system_message
