"""Tests for the ``app.routers.ai`` parent aggregator.

Run from the ``tablescope-ai-api`` directory: ``pytest -q``.
"""

from __future__ import annotations

from fastapi import FastAPI

import app.routers.ai as ai
import app.routers.ai_intelligence_plan as ai_intelligence_plan
import app.routers.ai_shared as ai_shared

EXPECTED_PATHS = {
    "/ai/actions/draft",
    "/ai/analyze-file",
    "/ai/ask",
    "/ai/dashboard/suggest",
    "/ai/dashboard/suggest-multi",
    "/ai/document/profile",
    "/ai/family/summarize",
    "/ai/grounding/search",
    "/ai/index/document",
    "/ai/index/reference",
    "/ai/intelligence/conversation-turn",
    "/ai/intelligence/interpret",
    "/ai/intelligence/investigate-step",
    "/ai/intelligence/knowledge-graph",
    "/ai/intelligence/plan",
    "/ai/intelligence/project-insight",
    "/ai/intelligence/repair-sql-step",
    "/ai/intelligence/select-insight-card",
    "/ai/project/relationships/generate",
    "/ai/project/scopes/analyze",
    "/ai/query/generate",
    "/ai/query/match",
    "/ai/reference-library/suggest",
    "/ai/reference-library/summarize",
    "/ai/speech/transcribe",
}


def test_every_feature_route_is_mounted_once_under_ai():
    app = FastAPI()
    app.include_router(ai.router)
    schema = app.openapi()

    assert set(schema["paths"]) == EXPECTED_PATHS
    for path, operations in schema["paths"].items():
        assert set(operations) == {"post"}, path
        assert operations["post"]["tags"] == ["AI"], path


def test_patching_the_aggregator_reaches_the_feature_modules(monkeypatch):
    """Callers patch names on ``app.routers.ai``; endpoints live elsewhere."""
    sentinel = object()
    monkeypatch.setattr(ai, "verify_signature", sentinel)
    assert ai_intelligence_plan.verify_signature is sentinel

    monkeypatch.setattr(ai, "_repair_truncated_json", sentinel)
    assert ai_shared._repair_truncated_json is sentinel


def test_patch_is_undone_everywhere(monkeypatch):
    original = ai_intelligence_plan.verify_signature
    with monkeypatch.context() as patch:
        patch.setattr(ai, "verify_signature", lambda *a, **k: None)
        assert ai_intelligence_plan.verify_signature is not original
    assert ai_intelligence_plan.verify_signature is original
