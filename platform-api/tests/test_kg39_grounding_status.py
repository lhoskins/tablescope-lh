"""KG-39: Knowledge Graph context collection must distinguish "the graph
legitimately has no content yet" from "loading the graph failed" -- both
previously returned the identical empty shape, so nothing downstream could
tell a healthy empty project apart from a degraded one, and every consumer
proceeded as if fully grounded either way.

Run from ``platform-api``: ``pytest -q tests/test_kg39_grounding_status.py``.
"""

from __future__ import annotations

import logging

import pytest

from app.services import knowledge_graph_ai_context as kgc

pytestmark = pytest.mark.asyncio


async def test_grounding_status_ok_for_a_legitimately_empty_project(monkeypatch):
    async def _fake_load(session, *, tenant_id, project_id):
        return [], []

    monkeypatch.setattr(kgc, "_load_stored_graph", _fake_load)
    result = await kgc.collect_knowledge_graph_ai_context(
        None, tenant_id=1, project_id=7, surface="business_insights",
    )
    assert result["grounding_status"] == "ok"


async def test_grounding_status_ok_for_a_real_populated_result(monkeypatch):
    nodes = [
        {"id": 1, "node_type": "risk", "name": "Overdue CAPAs",
         "source_type": None, "source_id": None, "properties": {"confidence": 0.9}},
    ]

    async def _fake_load(session, *, tenant_id, project_id):
        return nodes, []

    monkeypatch.setattr(kgc, "_load_stored_graph", _fake_load)
    result = await kgc.collect_knowledge_graph_ai_context(
        None, tenant_id=1, project_id=7, surface="business_insights",
    )
    assert result["grounding_status"] == "ok"
    assert result["risks"]


async def test_grounding_status_unavailable_when_loading_the_graph_fails(monkeypatch, caplog):
    async def _fake_load(session, *, tenant_id, project_id):
        raise RuntimeError("db exploded")

    monkeypatch.setattr(kgc, "_load_stored_graph", _fake_load)
    with caplog.at_level(logging.WARNING):
        result = await kgc.collect_knowledge_graph_ai_context(
            None, tenant_id=1, project_id=7, surface="business_insights",
        )
    assert result["grounding_status"] == "unavailable"
    # Every other bucket still comes back as a safe empty shape.
    assert result["risks"] == []
    assert result["opportunities"] == []
    # KG-39: this failure must be logged distinctly, not swallowed silently.
    assert any("degraded" in r.message.lower() for r in caplog.records)


async def test_degraded_status_never_silently_looks_like_success(monkeypatch):
    """A caller that only checks for a non-empty bucket (the old failure
    mode) would treat a degraded and a healthy-empty result identically --
    grounding_status is the one field that must always differ."""
    async def _fake_load_fails(session, *, tenant_id, project_id):
        raise RuntimeError("boom")

    async def _fake_load_empty(session, *, tenant_id, project_id):
        return [], []

    monkeypatch.setattr(kgc, "_load_stored_graph", _fake_load_fails)
    failed_result = await kgc.collect_knowledge_graph_ai_context(
        None, tenant_id=1, project_id=7, surface="project_insights",
    )
    monkeypatch.setattr(kgc, "_load_stored_graph", _fake_load_empty)
    empty_result = await kgc.collect_knowledge_graph_ai_context(
        None, tenant_id=1, project_id=7, surface="project_insights",
    )

    # Every other key is identical between the two -- grounding_status is
    # the only signal that distinguishes them.
    assert {k: v for k, v in failed_result.items() if k != "grounding_status"} == {
        k: v for k, v in empty_result.items() if k != "grounding_status"
    }
    assert failed_result["grounding_status"] != empty_result["grounding_status"]
