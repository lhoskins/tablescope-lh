"""KG-18: dashboard->query lineage should come from a widget's own stored
``dataSource.queryId`` binding, not only from KPI phrase matching against
free text. A dashboard that embeds a widget bound to a specific saved query
must produce a direct, deduplicated edge to that query's node.

Run from `platform-api`: `pytest -q tests/test_kg18_dashboard_widget_lineage.py`.
"""

from __future__ import annotations

import pytest

from app.models.dashboard import Dashboard
from app.models.project import Project
from app.models.saved_query import SavedQuery
from app.services.knowledge_graph_context.collectors import collect_structural_graph
from app.services.knowledge_graph_context.graph_primitives import (
    _REL_DASHBOARD_USES_QUERY,
)

pytestmark = pytest.mark.anyio


async def _seed_project(db_session, *, tenant_id: int) -> int:
    project = Project(tenant_id=tenant_id, owner_id=1, name="Widget Lineage Project", is_shared=False)
    db_session.add(project)
    await db_session.flush()
    return project.id


async def test_widget_bound_to_a_query_produces_a_direct_uses_query_edge(db_session):
    tenant_id = 1801
    project_id = await _seed_project(db_session, tenant_id=tenant_id)

    query = SavedQuery(
        project_id=project_id, owner_id=1, name="Churn by Segment", sql_text="SELECT 1",
    )
    db_session.add(query)
    await db_session.flush()

    dashboard = Dashboard(
        tenant_id=tenant_id, project_id=project_id, owner_id=1,
        name="Retention Dashboard",
        config={
            "widgets": [
                {
                    "id": "w1", "title": "Churn Chart", "type": "chart",
                    "dataSource": {"kind": "query", "queryId": query.id},
                }
            ]
        },
    )
    db_session.add(dashboard)
    await db_session.flush()

    _nodes, edges, _hub_key = await collect_structural_graph(
        db_session, tenant_id=tenant_id, project_id=project_id,
    )
    uses_query_edges = [e for e in edges if e["relationship_type"] == _REL_DASHBOARD_USES_QUERY]
    assert len(uses_query_edges) == 1
    edge = uses_query_edges[0]
    assert edge["from_node_id"] == f"s:dashboard:{dashboard.id}"
    assert edge["to_node_id"] == f"s:query:{query.id}"


async def test_dashboard_with_no_widget_bindings_produces_no_uses_query_edge(db_session):
    tenant_id = 1802
    project_id = await _seed_project(db_session, tenant_id=tenant_id)

    dashboard = Dashboard(
        tenant_id=tenant_id, project_id=project_id, owner_id=1,
        name="Static Dashboard", config={"widgets": [{"id": "w1", "title": "No binding"}]},
    )
    db_session.add(dashboard)
    await db_session.flush()

    _nodes, edges, _hub_key = await collect_structural_graph(
        db_session, tenant_id=tenant_id, project_id=project_id,
    )
    uses_query_edges = [e for e in edges if e["relationship_type"] == _REL_DASHBOARD_USES_QUERY]
    assert uses_query_edges == []


async def test_multiple_widgets_bound_to_the_same_query_dedup_to_one_edge(db_session):
    tenant_id = 1803
    project_id = await _seed_project(db_session, tenant_id=tenant_id)

    query = SavedQuery(
        project_id=project_id, owner_id=1, name="Revenue", sql_text="SELECT 1",
    )
    db_session.add(query)
    await db_session.flush()

    dashboard = Dashboard(
        tenant_id=tenant_id, project_id=project_id, owner_id=1,
        name="Revenue Dashboard",
        config={
            "widgets": [
                {"id": "w1", "dataSource": {"kind": "query", "queryId": query.id}},
                {"id": "w2", "dataSource": {"kind": "query", "queryId": query.id}},
            ]
        },
    )
    db_session.add(dashboard)
    await db_session.flush()

    _nodes, edges, _hub_key = await collect_structural_graph(
        db_session, tenant_id=tenant_id, project_id=project_id,
    )
    uses_query_edges = [e for e in edges if e["relationship_type"] == _REL_DASHBOARD_USES_QUERY]
    assert len(uses_query_edges) == 1


async def test_malformed_widget_config_shapes_are_ignored_without_error(db_session):
    tenant_id = 1804
    project_id = await _seed_project(db_session, tenant_id=tenant_id)

    dashboards = [
        Dashboard(
            tenant_id=tenant_id, project_id=project_id, owner_id=1,
            name="Null config", config=None,
        ),
        Dashboard(
            tenant_id=tenant_id, project_id=project_id, owner_id=1,
            name="Non-list widgets", config={"widgets": "not-a-list"},
        ),
        Dashboard(
            tenant_id=tenant_id, project_id=project_id, owner_id=1,
            name="Non-dict widget entries", config={"widgets": ["not-a-dict"]},
        ),
        Dashboard(
            tenant_id=tenant_id, project_id=project_id, owner_id=1,
            name="Non-dict dataSource", config={"widgets": [{"id": "w1", "dataSource": "oops"}]},
        ),
        Dashboard(
            tenant_id=tenant_id, project_id=project_id, owner_id=1,
            name="Unknown queryId",
            config={"widgets": [{"id": "w1", "dataSource": {"kind": "query", "queryId": 999999}}]},
        ),
    ]
    db_session.add_all(dashboards)
    await db_session.flush()

    nodes, edges, _hub_key = await collect_structural_graph(
        db_session, tenant_id=tenant_id, project_id=project_id,
    )
    dashboard_nodes = [n for n in nodes if n["source_type"] == "dashboard"]
    assert len(dashboard_nodes) == len(dashboards)
    uses_query_edges = [e for e in edges if e["relationship_type"] == _REL_DASHBOARD_USES_QUERY]
    assert uses_query_edges == []
