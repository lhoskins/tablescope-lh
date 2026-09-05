"""KG-37: make AI-context selection question-aware.

Validated gap: ``_ranked`` (used by every bucket in
``collect_knowledge_graph_ai_context``) only ever sorted by a node's own
static confidence -- a question like "why is on-time delivery slipping for
our suppliers?" had no influence on which risks/gaps/KPIs made it into a
capped, deduped bucket, so the most relevant item to what was actually asked
could be pushed out by an unrelated but higher-confidence one.

Run from ``platform-api``:
``pytest -q tests/test_kg37_question_aware_context.py``.
"""

from __future__ import annotations

import pytest

from app.services import knowledge_graph_ai_context as kgc


def _node(nid, ntype, name, *, conf, summary=""):
    props: dict = {"confidence": conf}
    if summary:
        props["summary"] = summary
    return {
        "id": nid, "node_type": ntype, "name": name,
        "source_type": None, "source_id": None, "properties": props,
    }


def _graph():
    nodes = [
        _node(1, "risk", "Supplier scorecard delays", conf=0.6,
              summary="On-time delivery has been slipping for key suppliers."),
        _node(2, "risk", "Unrelated compliance gap", conf=0.95,
              summary="A different, unrelated finding."),
    ]
    return nodes, []


async def _collect(monkeypatch, nodes, edges, **kw):
    async def _fake_load(session, *, tenant_id, project_id):
        return nodes, edges

    monkeypatch.setattr(kgc, "_load_stored_graph", _fake_load)
    return await kgc.collect_knowledge_graph_ai_context(
        None, tenant_id=1, project_id=7, **kw
    )


@pytest.mark.asyncio
async def test_no_question_ranks_by_confidence_only(monkeypatch):
    nodes, edges = _graph()
    out = await _collect(monkeypatch, nodes, edges)
    titles = [r["title"] for r in out["risks"]]
    assert titles == ["Unrelated compliance gap", "Supplier scorecard delays"]


@pytest.mark.asyncio
async def test_relevant_question_promotes_the_lower_confidence_matching_item(monkeypatch):
    nodes, edges = _graph()
    out = await _collect(
        monkeypatch, nodes, edges,
        question="Why is on-time delivery slipping for our suppliers?",
    )
    titles = [r["title"] for r in out["risks"]]
    assert titles == ["Supplier scorecard delays", "Unrelated compliance gap"]


def test_question_keywords_drops_stopwords_and_short_words():
    keywords = kgc._question_keywords("What is the status of on-time delivery?")
    assert "status" in keywords
    assert "delivery" in keywords
    for stopword in ("what", "is", "the", "of", "on"):
        assert stopword not in keywords


def test_question_keywords_empty_for_no_question():
    assert kgc._question_keywords(None) == frozenset()
    assert kgc._question_keywords("") == frozenset()
