"""KG-29: temporal consistency -- an insight card cannot be justified
solely by expired guidance without a warning.

Validated gap: ``AIProjectGraphNode``/``Edge`` carry no timestamp beyond
``created_at``, and no card/insight anywhere checked its cited evidence's
own freshness at build/render time -- distinct from the whole-graph
staleness fingerprint (KG-13/KG-44), which only detects that *something*
changed, not that a specific card's specific evidence has gone stale. A
freshly-built graph already excludes an expired reference document from
the active set (KG-20), but a cached card built before that document
expired kept citing it with no warning, indefinitely, until the project's
next rebuild.

Run from ``platform-api``: ``pytest -q tests/test_kg29_temporal_consistency.py``.
"""

from __future__ import annotations

import pytest

from app.models.project import Project
from app.models.reference_library import TIER_PROJECT, ReferenceDocument
from app.services.knowledge_graph.cards import _build_card_for_node
from app.services.knowledge_graph_context.collectors import collect_structural_graph

pytestmark = pytest.mark.anyio


def _node(node_id, node_type, *, properties=None):
    return {
        "id": node_id, "type": node_type, "label": node_type,
        "properties": properties or {}, "graphKey": f"{node_type}:{node_id}",
        "layer": "evidence" if node_type == "reference_document" else "semantic",
        "displayGroup": "", "severity": "info", "summary": "", "businessValue": "",
        "businessQuestion": "", "confidence": 0.8,
    }


def _risk_node(node_id):
    n = _node(node_id, "risk")
    n["layer"] = "semantic"
    return n


def _edge(edge_id, from_id, to_id):
    return {"id": edge_id, "from_node_id": from_id, "to_node_id": to_id, "relationship_type": "evidence_for"}


def test_card_flags_evidence_expired_when_a_reference_document_has_passed_expiration():
    risk = _risk_node("r1")
    ref = _node("d1", "reference_document", properties={"expiration_date": "2000-01-01"})
    nodes_by_id = {"r1": risk, "d1": ref}
    edges = [_edge("e1", "r1", "d1")]

    card = _build_card_for_node(risk, edges, nodes_by_id)
    assert card is not None
    assert card["evidenceExpired"] is True


def test_card_does_not_flag_a_reference_document_with_no_expiration():
    risk = _risk_node("r2")
    ref = _node("d2", "reference_document", properties={"expiration_date": None})
    nodes_by_id = {"r2": risk, "d2": ref}
    edges = [_edge("e2", "r2", "d2")]

    card = _build_card_for_node(risk, edges, nodes_by_id)
    assert card is not None
    assert card["evidenceExpired"] is False


def test_card_does_not_flag_a_reference_document_expiring_in_the_future():
    risk = _risk_node("r3")
    ref = _node("d3", "reference_document", properties={"expiration_date": "2999-01-01"})
    nodes_by_id = {"r3": risk, "d3": ref}
    edges = [_edge("e3", "r3", "d3")]

    card = _build_card_for_node(risk, edges, nodes_by_id)
    assert card is not None
    assert card["evidenceExpired"] is False


async def _seed_project(db_session, *, tenant_id: int) -> int:
    project = Project(tenant_id=tenant_id, owner_id=1, name="Temporal Project", is_shared=False)
    db_session.add(project)
    await db_session.flush()
    return project.id


async def test_reference_document_node_carries_its_own_expiration_date(db_session):
    tenant_id = 2901
    project_id = await _seed_project(db_session, tenant_id=tenant_id)

    doc = ReferenceDocument(
        tier=TIER_PROJECT, project_id=project_id, tenant_id=tenant_id,
        title="Project Procedure", status="active",
    )
    db_session.add(doc)
    await db_session.flush()

    nodes, _edges, _hub_key = await collect_structural_graph(
        db_session, tenant_id=tenant_id, project_id=project_id,
    )
    ref_nodes = [n for n in nodes if n["source_type"] == "reference_document"]
    assert len(ref_nodes) == 1
    assert "expiration_date" in ref_nodes[0]["properties"]
    assert "effective_date" in ref_nodes[0]["properties"]
