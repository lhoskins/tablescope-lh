"""An Ollama-side failure while judging Insight Card relevance must degrade
to a clean decline (insight_id=None), not an unhandled exception -- the
caller (platform-api's insight_card_match.py) already treats a decline and
an unreachable selector identically, so there is nothing gained by letting
this escape as an unhandled 500 in the ai-server's own logs.

Run from ``tablescope-ai-api``: ``pytest -q tests/test_insight_card_selector_llm_failure.py``.
"""

from __future__ import annotations

import asyncio

import httpx

import app.routers.ai as ai
from app.models.schemas import InsightCardCandidate, SelectInsightCardRequest


def _req() -> SelectInsightCardRequest:
    return SelectInsightCardRequest(
        tenant_id=1,
        user_id=1,
        project_id=1,
        question="Why is material cost increasing?",
        candidates=[
            InsightCardCandidate(insight_id="abc123", title="Material cost on the rise"),
        ],
    )


def test_llm_failure_degrades_to_a_clean_decline(monkeypatch) -> None:
    monkeypatch.setattr(ai, "verify_signature", lambda *a, **k: None)
    monkeypatch.setattr(ai, "update_activity", lambda *a, **k: None)

    async def fake_generate(**kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(ai.llm_client, "generate", fake_generate)

    resp = asyncio.run(ai.select_insight_card(_req()))

    assert resp.insight_id is None
    assert resp.confidence == 0.0
