"""An Ollama-side failure during SQL generation must become a structured
503 with a real reason, not an unhandled exception that FastAPI turns into
a bare, detail-less 500 -- see ai_query_generate.py's generate_sql_endpoint.

Run from ``tablescope-ai-api``: ``pytest -q tests/test_ai_query_generate_llm_failure.py``.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import HTTPException

import app.routers.ai as ai
from app.models.schemas import GenerateSQLRequest


class _FakeContext:
    allowed_context = {"metadata": []}


@pytest.fixture(autouse=True)
def _patch_endpoint(monkeypatch):
    monkeypatch.setattr(ai, "verify_signature", lambda *a, **k: None)
    monkeypatch.setattr(ai, "update_activity", lambda *a, **k: None)

    async def fake_build_context(**kwargs):
        return _FakeContext()

    monkeypatch.setattr(ai.context_builder, "build_context", fake_build_context)
    monkeypatch.setattr(ai.context_builder, "context_to_prompt_text", lambda ctx: "")


def _req() -> GenerateSQLRequest:
    return GenerateSQLRequest(
        tenant_id=1,
        user_id=1,
        project_id=1,
        prompt="Why is material cost increasing?",
        allowed_tables=["spend"],
    )


def test_llm_transport_failure_becomes_structured_503(monkeypatch) -> None:
    async def fake_generate_sql(**kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(ai.llm_client, "generate_sql", fake_generate_sql)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(ai.generate_sql_endpoint(_req()))

    assert exc_info.value.status_code == 503
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert "reason" in detail and "connection refused" in detail["reason"]


def test_llm_malformed_response_becomes_structured_503(monkeypatch) -> None:
    async def fake_generate_sql(**kwargs):
        raise KeyError("response")

    monkeypatch.setattr(ai.llm_client, "generate_sql", fake_generate_sql)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(ai.generate_sql_endpoint(_req()))

    assert exc_info.value.status_code == 503


def test_repair_llm_failure_also_becomes_structured_503(monkeypatch) -> None:
    async def fake_generate_sql(**kwargs):
        return 'SELECT "x" FROM does_not_exist'

    async def fake_repair_sql(**kwargs):
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(ai.llm_client, "generate_sql", fake_generate_sql)
    monkeypatch.setattr(ai.llm_client, "repair_sql", fake_repair_sql)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(ai.generate_sql_endpoint(_req()))

    assert exc_info.value.status_code == 503
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert "timed out" in detail["reason"]
