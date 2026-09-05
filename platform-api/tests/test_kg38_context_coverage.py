"""KG-38: report context omissions and truncation downstream.

Validated gap: ``collect_knowledge_graph_ai_context`` ranked and capped each
bucket (``max_items``) with no record of how much was left out -- a caller
could never tell "the graph legitimately had only 2 risks" apart from "there
were 20 risks and only 5 fit the cap." ``context_coverage`` records, per
bucket, how many candidates existed before ranking/capping (``available``)
versus how many actually made it into the returned context (``selected``).

Run from ``platform-api``: ``pytest -q tests/test_kg38_context_coverage.py``.
"""

from __future__ import annotations

import pytest

from app.services import knowledge_graph_ai_context as kgc


def _node(nid, ntype, name, *, conf):
    return {
        "id": nid, "node_type": ntype, "name": name,
        "source_type": None, "source_id": None,
        "properties": {"confidence": conf},
    }


async def _collect(monkeypatch, nodes, edges, **kw):
    async def _fake_load(session, *, tenant_id, project_id):
        return nodes, edges

    monkeypatch.setattr(kgc, "_load_stored_graph", _fake_load)
    return await kgc.collect_knowledge_graph_ai_context(
        None, tenant_id=1, project_id=7, **kw
    )


@pytest.mark.asyncio
async def test_coverage_reports_truncation_when_more_items_exist_than_the_cap(monkeypatch):
    nodes = [_node(i, "risk", f"Risk {i}", conf=0.5) for i in range(5)]
    out = await _collect(monkeypatch, nodes, [], max_items=3)
    assert out["context_coverage"]["risks"] == {"available": 5, "selected": 3}
    assert len(out["risks"]) == 3


@pytest.mark.asyncio
async def test_coverage_shows_no_truncation_when_everything_fits(monkeypatch):
    nodes = [_node(1, "risk", "Only risk", conf=0.9)]
    out = await _collect(monkeypatch, nodes, [], max_items=20)
    assert out["context_coverage"]["risks"] == {"available": 1, "selected": 1}


@pytest.mark.asyncio
async def test_coverage_is_empty_for_an_empty_graph(monkeypatch):
    out = await _collect(monkeypatch, [], [])
    assert out["context_coverage"] == {}
