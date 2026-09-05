"""KG-28: relationship cardinality and join-quality evidence.

Validated gap: ``SavedQuery.left_column``/``right_column`` only capture the
join-builder UI's two-table case, and ``app/services/sql_lineage.py`` (built
for KG-17) only extracted *which tables* a query references, not *which
columns* its joins actually key on. A hand-written/AI-generated query with
joins buried anywhere in its SQL had zero join-key evidence at all.

Home Intelligence's ``query_helpers.py`` already computes real cardinality/
overlap signals (``_cardinality``, ``_containment``) from sampled data, but
only ephemerally for one widget-planning response -- persisting that
execution-dependent evidence (null rates, duplicate rates, one-to-many
classification, validation samples) onto a durable record is a materially
larger, separate effort, deliberately out of scope here. This closes the
purely-parseable half of the ask: the join *keys* themselves, extractable
from SQL text alone with no query execution needed.

Run from ``platform-api``: ``pytest -q tests/test_kg28_join_key_evidence.py``.
"""

from __future__ import annotations

import pytest

from app.models.project import Project
from app.models.saved_query import SavedQuery
from app.services.knowledge_graph_context.collectors import collect_structural_graph
from app.services.sql_lineage import extract_join_keys

pytestmark = pytest.mark.anyio


def test_extract_join_keys_finds_a_simple_join_condition():
    sql = "SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id"
    keys = extract_join_keys(sql)
    assert len(keys) == 1
    assert keys[0] == {
        "left_table": "orders", "left_column": "customer_id",
        "right_table": "customers", "right_column": "id",
        "join_type": "INNER",
    }


def test_extract_join_keys_reports_the_join_type():
    sql = "SELECT * FROM orders o LEFT JOIN customers c ON o.customer_id = c.id"
    keys = extract_join_keys(sql)
    assert len(keys) == 1
    assert keys[0]["join_type"] == "LEFT"


def test_extract_join_keys_excludes_non_join_filter_conditions_in_the_on_clause():
    sql = (
        "SELECT * FROM orders o "
        "JOIN order_items oi ON oi.order_id = o.id AND oi.active = true"
    )
    keys = extract_join_keys(sql)
    assert len(keys) == 1
    assert keys[0]["left_column"] == "order_id"
    assert keys[0]["right_column"] == "id"


def test_extract_join_keys_handles_multiple_joins():
    sql = (
        "SELECT * FROM orders o "
        "JOIN customers c ON o.customer_id = c.id "
        "JOIN order_items oi ON oi.order_id = o.id"
    )
    keys = extract_join_keys(sql)
    assert len(keys) == 2


def test_extract_join_keys_is_empty_and_safe_for_no_joins_or_unparsable_sql():
    assert extract_join_keys("SELECT * FROM orders") == []
    assert extract_join_keys("not even ( valid sql") == []
    assert extract_join_keys(None) == []
    assert extract_join_keys("") == []


async def _seed_project(db_session, *, tenant_id: int) -> int:
    project = Project(tenant_id=tenant_id, owner_id=1, name="Join Key Project", is_shared=False)
    db_session.add(project)
    await db_session.flush()
    return project.id


async def test_saved_query_node_carries_join_key_evidence(db_session):
    tenant_id = 2801
    project_id = await _seed_project(db_session, tenant_id=tenant_id)

    query = SavedQuery(
        project_id=project_id, owner_id=1, name="Orders with Customers",
        sql_text="SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id",
    )
    db_session.add(query)
    await db_session.flush()

    nodes, _edges, _hub_key = await collect_structural_graph(
        db_session, tenant_id=tenant_id, project_id=project_id,
    )
    query_nodes = [n for n in nodes if n["source_type"] == "saved_query"]
    assert len(query_nodes) == 1
    join_keys = query_nodes[0]["properties"].get("join_keys")
    assert join_keys == [{
        "left_table": "orders", "left_column": "customer_id",
        "right_table": "customers", "right_column": "id",
        "join_type": "INNER",
    }]


async def test_saved_query_node_has_no_join_keys_property_when_query_has_no_join(db_session):
    tenant_id = 2802
    project_id = await _seed_project(db_session, tenant_id=tenant_id)

    query = SavedQuery(
        project_id=project_id, owner_id=1, name="Simple Select",
        sql_text="SELECT * FROM orders",
    )
    db_session.add(query)
    await db_session.flush()

    nodes, _edges, _hub_key = await collect_structural_graph(
        db_session, tenant_id=tenant_id, project_id=project_id,
    )
    query_nodes = [n for n in nodes if n["source_type"] == "saved_query"]
    assert len(query_nodes) == 1
    assert "join_keys" not in query_nodes[0]["properties"]
