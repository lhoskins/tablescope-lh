"""KG-17: saved-query table lineage must come from parsing ``sql_text``,
not only from the join-builder's ``left_datasource``/``right_datasource``
fields -- those are only ever populated by the two-table join-builder UI,
so a hand-written or AI-generated query (arbitrary SQL, any number of
tables, joins buried in a CTE) previously produced zero lineage edges no
matter what tables it actually read.

Run from `platform-api`:
`pytest -q tests/test_kg17_sql_lineage.py`.
"""

from __future__ import annotations

import pytest

from app.models.database_data_source import DatabaseDataSource
from app.models.project import Project
from app.models.saved_query import SavedQuery
from app.services.knowledge_graph_context.collectors import collect_structural_graph
from app.services.knowledge_graph_context.graph_primitives import _REL_QUERY_READS
from app.services.sql_lineage import extract_referenced_tables

pytestmark = pytest.mark.anyio


def test_extract_referenced_tables_finds_every_table_in_a_multi_join_query():
    sql = """
        SELECT o.id, c.name, p.sku
        FROM orders o
        JOIN customers c ON c.id = o.customer_id
        JOIN order_items oi ON oi.order_id = o.id
        JOIN products p ON p.id = oi.product_id
    """
    assert extract_referenced_tables(sql) == {"orders", "customers", "order_items", "products"}


def test_extract_referenced_tables_excludes_cte_names():
    sql = """
        WITH recent_orders AS (SELECT * FROM orders WHERE created_at > '2024-01-01')
        SELECT * FROM recent_orders JOIN customers ON customers.id = recent_orders.customer_id
    """
    tables = extract_referenced_tables(sql)
    assert tables == {"orders", "customers"}
    assert "recent_orders" not in {t.lower() for t in tables}


def test_extract_referenced_tables_is_empty_and_safe_for_unparsable_sql():
    assert extract_referenced_tables("not even ( valid sql") == set()
    assert extract_referenced_tables(None) == set()
    assert extract_referenced_tables("") == set()


async def _seed_project(db_session, *, tenant_id: int) -> int:
    project = Project(tenant_id=tenant_id, owner_id=1, name="SQL Lineage Project", is_shared=False)
    db_session.add(project)
    await db_session.flush()
    return project.id


async def test_hand_written_sql_query_with_no_join_builder_fields_still_gets_lineage(
    db_session,
):
    tenant_id = 1701
    project_id = await _seed_project(db_session, tenant_id=tenant_id)

    ds = DatabaseDataSource(
        tenant_id=tenant_id, project_id=project_id,
        db_type="postgres", table_name="orders", display_name="orders",
        host="db.internal", port=5432, database_name="sales", username="reader",
        teiid_model_name="m", teiid_table_name="t", teiid_view_name="v",
        teiid_jndi_name="j", archived=False,
    )
    db_session.add(ds)
    await db_session.flush()

    query = SavedQuery(
        project_id=project_id, owner_id=1, name="Orders Report",
        sql_text="SELECT * FROM orders WHERE status = 'open'",
        ai_generated=True,
    )
    db_session.add(query)
    await db_session.flush()

    _nodes, edges, _hub_key = await collect_structural_graph(
        db_session, tenant_id=tenant_id, project_id=project_id,
    )
    reads_edges = [
        e for e in edges
        if e["relationship_type"] == _REL_QUERY_READS and e["from_node_id"] == f"s:query:{query.id}"
    ]
    assert len(reads_edges) == 1
    assert reads_edges[0]["to_node_id"] == f"s:datasource:db:{ds.id}"


async def test_sql_lineage_does_not_duplicate_a_join_builder_edge_to_the_same_target(
    db_session,
):
    tenant_id = 1702
    project_id = await _seed_project(db_session, tenant_id=tenant_id)

    ds = DatabaseDataSource(
        tenant_id=tenant_id, project_id=project_id,
        db_type="postgres", table_name="orders", display_name="orders",
        host="db.internal", port=5432, database_name="sales", username="reader",
        teiid_model_name="m", teiid_table_name="t", teiid_view_name="v",
        teiid_jndi_name="j", archived=False,
    )
    db_session.add(ds)
    await db_session.flush()

    query = SavedQuery(
        project_id=project_id, owner_id=1, name="Orders Join",
        left_datasource="orders", right_datasource=None,
        sql_text="SELECT * FROM orders",
    )
    db_session.add(query)
    await db_session.flush()

    _nodes, edges, _hub_key = await collect_structural_graph(
        db_session, tenant_id=tenant_id, project_id=project_id,
    )
    reads_edges = [
        e for e in edges
        if e["relationship_type"] == _REL_QUERY_READS and e["from_node_id"] == f"s:query:{query.id}"
    ]
    assert len(reads_edges) == 1


async def test_query_with_no_sql_text_and_no_join_builder_fields_gets_no_lineage_edges(
    db_session,
):
    tenant_id = 1703
    project_id = await _seed_project(db_session, tenant_id=tenant_id)

    query = SavedQuery(project_id=project_id, owner_id=1, name="Blank Query")
    db_session.add(query)
    await db_session.flush()

    _nodes, edges, _hub_key = await collect_structural_graph(
        db_session, tenant_id=tenant_id, project_id=project_id,
    )
    reads_edges = [
        e for e in edges
        if e["relationship_type"] == _REL_QUERY_READS and e["from_node_id"] == f"s:query:{query.id}"
    ]
    assert reads_edges == []
