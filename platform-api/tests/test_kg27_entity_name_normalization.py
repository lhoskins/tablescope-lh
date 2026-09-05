"""KG-27: canonical entity resolution with aliases -- confirmed to not
exist at all today (no alias/canonicalization mechanism for customers,
suppliers, sites, products, people, or processes; no group model; no
reviewer-confirmation workflow). Building the full ask (identifier/alias/
context-based resolution with human review) is a materially larger,
separate effort.

This closes the narrowest, safest, most concrete slice: both node-upsert
helpers that create entity nodes (``_upsert_node`` in
``document_processing_service/graph.py``, ``_upsert_typed_node`` in
``project_graph_service/graph_primitives.py``) matched on an *exact*
string, so "CMX", "cmx", and " CMX " each created a separate,
never-merged node for the same real-world entity -- exactly the failure
mode the review's Accept criterion names, at the trivial end of it.

Run from ``platform-api``:
``pytest -q tests/test_kg27_entity_name_normalization.py``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.services.document_processing_service.graph import _upsert_node
from app.services.project_graph_service.graph_primitives import _upsert_typed_node

T1, P1, U1 = 1, 10, 100


async def _node_count(session, tenant_id, project_id, node_type):
    res = await session.execute(
        text(
            "SELECT COUNT(*) FROM ai_project_graph_nodes "
            "WHERE tenant_id=:t AND project_id=:p AND node_type=:nt"
        ),
        {"t": tenant_id, "p": project_id, "nt": node_type},
    )
    return int(res.scalar() or 0)


@pytest.mark.asyncio
async def test_upsert_node_merges_differently_cased_and_padded_names(db_session):
    id1 = await _upsert_node(
        db_session, T1, P1, U1, node_type="site", name="CMX",
    )
    id2 = await _upsert_node(
        db_session, T1, P1, U1, node_type="site", name="cmx",
    )
    id3 = await _upsert_node(
        db_session, T1, P1, U1, node_type="site", name="  CMX  ",
    )
    await db_session.commit()

    assert id1 == id2 == id3
    assert await _node_count(db_session, T1, P1, "site") == 1


@pytest.mark.asyncio
async def test_upsert_node_still_creates_separate_nodes_for_different_names(db_session):
    await _upsert_node(db_session, T1, P1, U1, node_type="site", name="CMX")
    await _upsert_node(db_session, T1, P1, U1, node_type="site", name="Mexicali")
    await db_session.commit()

    assert await _node_count(db_session, T1, P1, "site") == 2


@pytest.mark.asyncio
async def test_upsert_typed_node_merges_differently_cased_and_padded_names(db_session):
    id1 = await _upsert_typed_node(
        db_session, T1, P1, U1, node_type="supplier", name="Acme Corp",
    )
    id2 = await _upsert_typed_node(
        db_session, T1, P1, U1, node_type="supplier", name="acme corp",
    )
    id3 = await _upsert_typed_node(
        db_session, T1, P1, U1, node_type="supplier", name=" Acme Corp ",
    )
    await db_session.commit()

    assert id1 == id2 == id3
    assert await _node_count(db_session, T1, P1, "supplier") == 1


@pytest.mark.asyncio
async def test_upsert_typed_node_still_creates_separate_nodes_for_different_names(db_session):
    await _upsert_typed_node(db_session, T1, P1, U1, node_type="supplier", name="Acme Corp")
    await _upsert_typed_node(db_session, T1, P1, U1, node_type="supplier", name="Other Corp")
    await db_session.commit()

    assert await _node_count(db_session, T1, P1, "supplier") == 2
