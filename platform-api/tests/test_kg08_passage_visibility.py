"""KG-08: derived content can never have broader visibility than its most
restrictive evidence -- a document passage/chunk node (KG-16,
``source_type == "ai_document_chunk"``) IS its parent document's evidence,
so it must be hidden from anyone the parent document itself is hidden from.

Confirmed gap: both ``filter_raw_graph_for_user`` (KG-06, pre-enrichment)
and ``filter_payload_for_viewer`` (KG-04, post-build) only ever matched
``source_type == "project_asset"`` when computing which node ids to hide --
a private document's own passage nodes carried the raw chunk text right
past the filter, only losing their connecting edge to the (correctly)
hidden document node, leaving them floating, still visible, disconnected
evidence.

Run from ``platform-api``: ``pytest -q tests/test_kg08_passage_visibility.py``.
"""

from __future__ import annotations

import pytest

from app.models.project import Project
from app.models.project_asset import ProjectAsset
from app.services.knowledge_graph.visibility import (
    filter_payload_for_viewer,
    filter_raw_graph_for_user,
)

pytestmark = pytest.mark.anyio


async def _seed_private_asset(db_session, *, tenant_id: int, owner_id: int) -> tuple[int, int]:
    project = Project(tenant_id=tenant_id, owner_id=owner_id, name="P")
    db_session.add(project)
    await db_session.flush()

    asset = ProjectAsset(
        tenant_id=tenant_id, project_id=project.id, owner_user_id=owner_id,
        asset_type="document", title="Private Doc", filename="d.pdf",
        storage_location="d.pdf", visibility="private",
    )
    db_session.add(asset)
    await db_session.flush()
    return project.id, asset.id


def _nodes_and_edges(asset_id: int) -> tuple[list[dict], list[dict]]:
    nodes = [
        {"id": "s:asset:1", "node_type": "document", "name": "Private Doc",
         "source_type": "project_asset", "source_id": asset_id, "properties": {}},
        {"id": "s:passage:1", "node_type": "document_passage", "name": "Private Doc — passage 1",
         "source_type": "ai_document_chunk", "source_id": 1,
         "properties": {"chunk_index": 0, "summary": "secret paragraph", "asset_id": asset_id}},
    ]
    edges = [
        {"id": "se:passage:1", "from_node_id": "s:asset:1", "to_node_id": "s:passage:1",
         "relationship_type": "has_passage"},
    ]
    return nodes, edges


async def test_filter_raw_graph_for_user_hides_passage_of_a_private_document(db_session):
    tenant_id = 1801
    _project_id, asset_id = await _seed_private_asset(db_session, tenant_id=tenant_id, owner_id=10)
    nodes, edges = _nodes_and_edges(asset_id)

    visible_nodes, visible_edges = await filter_raw_graph_for_user(
        db_session, nodes, edges, tenant_id=tenant_id, user_id=99, role="member",
    )
    assert visible_nodes == []
    assert visible_edges == []

    owner_nodes, owner_edges = await filter_raw_graph_for_user(
        db_session, nodes, edges, tenant_id=tenant_id, user_id=10, role="member",
    )
    assert {n["id"] for n in owner_nodes} == {"s:asset:1", "s:passage:1"}
    assert len(owner_edges) == 1


async def test_filter_payload_for_viewer_hides_passage_of_a_private_document(db_session):
    tenant_id = 1802
    _project_id, asset_id = await _seed_private_asset(db_session, tenant_id=tenant_id, owner_id=10)
    nodes, edges = _nodes_and_edges(asset_id)

    payload = {
        "centerNode": None,
        "nodes": nodes,
        "edges": [{"id": e["id"], "source": e["from_node_id"], "target": e["to_node_id"]} for e in edges],
        "insightCards": [],
        "gaps": [],
        "recommendedActions": [],
        "tracePaths": [],
        "stats": {"nodeCount": 2, "edgeCount": 1, "cardCount": 0, "gapCount": 0, "byDisplayGroup": {}},
    }

    filtered = await filter_payload_for_viewer(
        db_session, payload, tenant_id=tenant_id, user_id=99, role="member",
    )
    assert filtered["nodes"] == []
    assert filtered["edges"] == []

    unfiltered = await filter_payload_for_viewer(
        db_session, payload, tenant_id=tenant_id, user_id=10, role="member",
    )
    assert {n["id"] for n in unfiltered["nodes"]} == {"s:asset:1", "s:passage:1"}
