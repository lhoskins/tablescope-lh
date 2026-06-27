"""Tests for the Knowledge Graph AI context collector.

``collect_knowledge_graph_ai_context`` turns the project's stored graph into a
compact, ranked, deduped summary the AI server uses to steer dashboard/query
generation. These tests stub the graph loader so they stay fast and focus on
the collection/classification/ranking logic (isolation, measured vs recommended
KPIs, reference-library-is-not-a-datasource, dedup + confidence ranking).
"""

from __future__ import annotations

import pytest

from app.services import knowledge_graph_ai_context as kgc


def _node(nid, ntype, name, *, conf=None, summary="", extra_props=None):
    props: dict = {}
    if conf is not None:
        props["confidence"] = conf
    if summary:
        props["summary"] = summary
    if extra_props:
        props.update(extra_props)
    return {
        "id": nid, "node_type": ntype, "name": name,
        "source_type": None, "source_id": None, "properties": props,
    }


def _edge(eid, a, b, rel, conf):
    return {
        "id": eid, "from_node_id": a, "to_node_id": b,
        "relationship_type": rel, "confidence": conf, "evidence": {},
    }


def _graph():
    nodes = [
        _node(1, "risk", "CAPA closures slipping", conf=0.9, summary="Overdue CAPAs."),
        _node(2, "gap", "No supplier-scorecard query", conf=0.8, summary="Missing measure."),
        _node(3, "policy", "Quality Manual", conf=0.95, summary="Governs CAPA."),
        _node(4, "reference_document", "ISO 9001", conf=0.7, summary="Standard."),
        _node(5, "kpi", "On-time Closure", conf=0.85),
        _node(6, "kpi", "First-pass Yield", conf=0.6,
              extra_props={"kpiStatus": "recommended"}),
        _node(7, "saved_query", "Open CAPAs", conf=0.8),
        _node(8, "data_source", "capa_table", conf=0.8),
        _node(9, "dashboard", "CAPA Dashboard", conf=0.8),
    ]
    edges = [
        _edge(1, 7, 5, "measures", 0.9),      # query measures On-time Closure
        _edge(2, 7, 8, "reads_from", 0.9),    # query reads capa_table
        _edge(3, 9, 5, "visualizes", 0.9),    # dashboard visualizes On-time Closure
    ]
    return nodes, edges


async def _collect(monkeypatch, nodes, edges, **kw):
    async def _fake_load(session, *, tenant_id, project_id):
        return nodes, edges

    monkeypatch.setattr(kgc, "_load_stored_graph", _fake_load)
    return await kgc.collect_knowledge_graph_ai_context(
        None, tenant_id=1, project_id=7, **kw
    )


@pytest.mark.asyncio
async def test_empty_graph_returns_empty_buckets(monkeypatch):
    out = await _collect(monkeypatch, [], [])
    for key in (
        "risks", "opportunities", "gaps", "warnings", "recommended_kpis",
        "measured_kpis", "governing_documents", "reference_guidance",
    ):
        assert out[key] == []


@pytest.mark.asyncio
async def test_collects_risks_gaps_and_documents(monkeypatch):
    nodes, edges = _graph()
    out = await _collect(monkeypatch, nodes, edges)
    assert [r["title"] for r in out["risks"]] == ["CAPA closures slipping"]
    assert [g["title"] for g in out["gaps"]] == ["No supplier-scorecard query"]
    assert "Quality Manual" in [d["title"] for d in out["governing_documents"]]


@pytest.mark.asyncio
async def test_measured_vs_recommended_kpi(monkeypatch):
    nodes, edges = _graph()
    out = await _collect(monkeypatch, nodes, edges)
    measured = {k["title"] for k in out["measured_kpis"]}
    recommended = {k["title"] for k in out["recommended_kpis"]}
    assert "On-time Closure" in measured
    assert "First-pass Yield" in recommended
    # Measured KPI records what measures it (query and/or dashboard).
    otc = next(k for k in out["measured_kpis"] if k["title"] == "On-time Closure")
    assert "Open CAPAs" in otc["measured_by"] or "CAPA Dashboard" in otc["measured_by"]


@pytest.mark.asyncio
async def test_reference_document_is_guidance_not_datasource(monkeypatch):
    nodes, edges = _graph()
    out = await _collect(monkeypatch, nodes, edges)
    assert "ISO 9001" in [r["title"] for r in out["reference_guidance"]]
    # A reference document must never appear as a datasource relationship.
    for rel in out["datasource_relationships"]:
        assert rel["datasource"] != "ISO 9001"


@pytest.mark.asyncio
async def test_query_lineage_captured(monkeypatch):
    nodes, edges = _graph()
    out = await _collect(monkeypatch, nodes, edges)
    targets = {(ln["query"], ln["target"]) for ln in out["query_lineage"]}
    assert ("Open CAPAs", "On-time Closure") in targets
    assert ("Open CAPAs", "capa_table") in targets


@pytest.mark.asyncio
async def test_dedup_and_confidence_ranking(monkeypatch):
    nodes = [
        _node(1, "risk", "Duplicate risk", conf=0.5),
        _node(2, "risk", "Duplicate risk", conf=0.9),  # same title, deduped
        _node(3, "risk", "High risk", conf=0.95),
        _node(4, "risk", "Low risk", conf=0.4),
    ]
    out = await _collect(monkeypatch, nodes, [])
    titles = [r["title"] for r in out["risks"]]
    # Highest-confidence first, and the duplicate title appears once.
    assert titles == ["High risk", "Duplicate risk", "Low risk"]
    assert titles.count("Duplicate risk") == 1


@pytest.mark.asyncio
async def test_max_items_caps_results(monkeypatch):
    nodes = [_node(i, "risk", f"Risk {i}", conf=0.5 + i / 100) for i in range(30)]
    out = await _collect(monkeypatch, nodes, [], max_items=5)
    assert len(out["risks"]) == 5
