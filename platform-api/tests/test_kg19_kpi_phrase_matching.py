"""KG-19: KPI "measured by" detection must be word-boundary safe, not raw
substring matching. Confirmed gap: ``_phrase_in`` (and the underlying
``_norm``-based haystack) stripped all punctuation/spaces, so a short KPI
phrase like "Rate" could match as a fragment inside an unrelated word like
"Corporate" -- a false "measured" classification the review's item #19
specifically calls out ("similarly named KPIs do not cross-link").

Run from ``platform-api``: ``pytest -q tests/test_kg19_kpi_phrase_matching.py``.
"""

from __future__ import annotations

from app.models.ai_project_graph import AIProjectGraphNode
from app.models.project import Project
from app.models.saved_query import SavedQuery
from app.services.knowledge_graph_context import collect_structural_graph
from app.services.knowledge_graph_context.graph_primitives import _phrase_in


async def _seed_project(db_session, *, tenant_id: int = 1) -> int:
    project = Project(tenant_id=tenant_id, owner_id=1, name="Boeing Supplier QA")
    db_session.add(project)
    await db_session.flush()
    return project.id


def _kpi_node(**overrides):
    fields = dict(node_type="kpi", created_by=1, is_active=True)
    fields.update(overrides)
    return fields


async def test_short_kpi_phrase_does_not_match_inside_an_unrelated_word(db_session):
    """The confirmed bug: a KPI named "Rate" must not be considered measured
    by a query merely because its text contains "corporate", "accurate", or
    similar words that happen to contain "rate" as a substring."""
    tenant_id = 1
    project_id = await _seed_project(db_session, tenant_id=tenant_id)
    db_session.add(
        AIProjectGraphNode(
            tenant_id=tenant_id, project_id=project_id,
            **_kpi_node(name="Rate"),
        )
    )
    db_session.add(
        SavedQuery(
            project_id=project_id, owner_id=1,
            name="Corporate Quarterly Report",
            description="Accurate summary of moderate spend across sites.",
        )
    )
    await db_session.flush()

    nodes, edges, _hub = await collect_structural_graph(
        db_session, tenant_id=tenant_id, project_id=project_id,
    )
    kpi_node = next(n for n in nodes if n["node_type"] == "kpi")
    assert kpi_node["properties"]["kpiStatus"] == "recommended"
    assert not any(e["relationship_type"] == "measures" for e in edges)


async def test_multi_word_kpi_phrase_still_matches_a_real_measuring_query(db_session):
    """True positives must survive the tightened matching: a query whose
    name/description literally contains the KPI's full phrase still counts
    as measuring it."""
    tenant_id = 1
    project_id = await _seed_project(db_session, tenant_id=tenant_id)
    db_session.add(
        AIProjectGraphNode(
            tenant_id=tenant_id, project_id=project_id,
            **_kpi_node(name="On-time Delivery"),
        )
    )
    db_session.add(
        SavedQuery(
            project_id=project_id, owner_id=1,
            name="On-Time Delivery Dashboard Query",
        )
    )
    await db_session.flush()

    nodes, edges, _hub = await collect_structural_graph(
        db_session, tenant_id=tenant_id, project_id=project_id,
    )
    kpi_node = next(n for n in nodes if n["node_type"] == "kpi")
    assert kpi_node["properties"]["kpiStatus"] == "measured"
    assert any(e["relationship_type"] == "measures" for e in edges)


def test_phrase_in_rejects_fragment_matches_directly():
    assert _phrase_in({"rate"}, "corporate quarterly report") is False
    assert _phrase_in({"rate"}, "on time delivery rate report") is True


def test_phrase_in_requires_the_full_multi_word_phrase():
    assert _phrase_in({"on time delivery"}, "on time delivery dashboard") is True
    # Words present but not contiguous/in order -- not a real phrase match.
    assert _phrase_in({"on time delivery"}, "delivery time report, on demand") is False
