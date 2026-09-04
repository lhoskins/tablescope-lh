"""KG-42: an incremental rebuild must refresh AI insight cards for the
centres a change actually touches, instead of always carrying the active
snapshot's ``aiCardsByCenter`` over unchanged.

Run from `platform-api`: `pytest -q tests/test_kg42_incremental_card_refresh.py`.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.jwt import TokenClaims
from app.models import AIProjectGraphEdge, AIProjectGraphNode, Project
from app.services import knowledge_graph_ai as kg_ai
from app.services.knowledge_graph.snapshot import get_project_graph_snapshot
from app.services.knowledge_graph_lifecycle import KnowledgeGraphLifecycleManager
from app.services.knowledge_graph_lifecycle.incremental_cards import (
    affected_center_keys,
)

pytestmark = pytest.mark.anyio


# ── Unit-level: affected_center_keys itself ────────────────────────────────

def _node(nid, gkey, *, node_type="kpi", name=None) -> dict:
    return {
        "id": nid,
        "node_type": node_type,
        "name": name or gkey,
        "source_type": None,
        "source_id": None,
        "properties": {"graph_key": gkey},
    }


def test_unchanged_graph_needs_no_refresh_or_eviction():
    nodes = [_node(1, "kpi:a"), _node(2, "kpi:b")]
    cached = {"kpi:a": {"insightCards": []}, "kpi:b": {"insightCards": []}}
    refresh, stale = affected_center_keys(
        old_nodes=nodes, old_edges=[], new_nodes=nodes, new_edges=[],
        cached_cards_by_center=cached,
    )
    assert refresh == []
    assert stale == []


def test_newly_eligible_center_with_no_cache_needs_refresh():
    old_nodes = [_node(1, "kpi:a")]
    new_nodes = [_node(1, "kpi:a"), _node(2, "kpi:b")]
    cached = {"kpi:a": {"insightCards": []}}
    refresh, stale = affected_center_keys(
        old_nodes=old_nodes, old_edges=[], new_nodes=new_nodes, new_edges=[],
        cached_cards_by_center=cached,
    )
    assert refresh == ["kpi:b"]
    assert stale == []


def test_changed_center_node_needs_refresh():
    old_nodes = [_node(1, "kpi:a", name="Old Name")]
    new_nodes = [_node(1, "kpi:a", name="New Name")]
    cached = {"kpi:a": {"insightCards": []}}
    refresh, stale = affected_center_keys(
        old_nodes=old_nodes, old_edges=[], new_nodes=new_nodes, new_edges=[],
        cached_cards_by_center=cached,
    )
    assert refresh == ["kpi:a"]


def test_card_evidence_node_changing_refreshes_the_center_that_cited_it():
    # The center "kpi:a" is itself unchanged, but a card cached for it traced
    # to node 2 as evidence, and node 2's content changed underneath it.
    old_nodes = [_node(1, "kpi:a"), _node(2, "doc:b", node_type="document", name="Doc old")]
    new_nodes = [_node(1, "kpi:a"), _node(2, "doc:b", node_type="document", name="Doc new")]
    cached = {
        "kpi:a": {"insightCards": [{"traceToEvidence": {"nodeIds": [1, 2]}}]},
        "doc:b": {"insightCards": []},
    }
    refresh, stale = affected_center_keys(
        old_nodes=old_nodes, old_edges=[], new_nodes=new_nodes, new_edges=[],
        cached_cards_by_center=cached,
    )
    # kpi:a refreshes because its cached card's evidence changed; doc:b
    # refreshes because it is itself the node that changed.
    assert set(refresh) == {"kpi:a", "doc:b"}


def test_edge_change_touches_both_endpoints():
    nodes = [_node(1, "kpi:a"), _node(2, "doc:b", node_type="document")]
    old_edges = [{"id": "e1", "from_node_id": 1, "to_node_id": 2, "confidence": 0.5}]
    new_edges = [{"id": "e1", "from_node_id": 1, "to_node_id": 2, "confidence": 0.9}]
    cached = {
        "kpi:a": {"insightCards": [{"traceToEvidence": {"nodeIds": [1]}}]},
        "doc:b": {"insightCards": []},
    }
    refresh, stale = affected_center_keys(
        old_nodes=nodes, old_edges=old_edges, new_nodes=nodes, new_edges=new_edges,
        cached_cards_by_center=cached,
    )
    assert set(refresh) == {"kpi:a", "doc:b"}


def test_removed_center_is_evicted_not_refreshed():
    old_nodes = [_node(1, "kpi:a"), _node(2, "kpi:b")]
    new_nodes = [_node(1, "kpi:a")]
    cached = {"kpi:a": {"insightCards": []}, "kpi:b": {"insightCards": []}}
    refresh, stale = affected_center_keys(
        old_nodes=old_nodes, old_edges=[], new_nodes=new_nodes, new_edges=[],
        cached_cards_by_center=cached,
    )
    assert refresh == []
    assert stale == ["kpi:b"]


# ── Integration: run_incremental_rebuild only re-enriches the touched centre ──

def _manager(session: AsyncSession, tenant_id: int, user_id: int) -> KnowledgeGraphLifecycleManager:
    return KnowledgeGraphLifecycleManager(
        session,
        RequestContext(
            claims=TokenClaims(sub=str(user_id), tenant_id=tenant_id, user_id=user_id, role="editor")
        ),
    )


async def test_incremental_rebuild_only_reenriches_the_changed_center(db_session, monkeypatch):
    calls: list[str] = []

    async def _fake_cards(**kwargs):
        calls.append(kwargs["center"]["graph_key"])
        return []

    monkeypatch.setattr(kg_ai.ai, "is_enabled", lambda: True)
    monkeypatch.setattr(kg_ai.ai, "knowledge_graph_cards", _fake_cards)

    tenant_id, user_id = 201, 1
    project = Project(tenant_id=tenant_id, name="kg42 Project", owner_id=user_id, is_shared=False)
    db_session.add(project)
    await db_session.flush()

    node_a = AIProjectGraphNode(
        tenant_id=tenant_id, project_id=project.id, node_type="risk",
        name="Risk Alpha", properties={"graph_key": "risk:alpha"},
        created_by=user_id, is_active=True,
    )
    node_b = AIProjectGraphNode(
        tenant_id=tenant_id, project_id=project.id, node_type="document",
        name="Doc Beta", properties={"graph_key": "doc:beta"},
        created_by=user_id, is_active=True,
    )
    db_session.add_all([node_a, node_b])
    await db_session.flush()
    db_session.add(
        AIProjectGraphEdge(
            tenant_id=tenant_id, project_id=project.id,
            from_node_id=node_a.id, to_node_id=node_b.id,
            relationship_type="related", confidence=0.9,
            created_by=user_id, is_active=True,
        )
    )
    await db_session.flush()

    manager = _manager(db_session, tenant_id, user_id)
    build, _ = await manager.request_full_rebuild(project.id, requested_by=user_id)
    await db_session.commit()
    await db_session.refresh(build)
    await manager.run_full_rebuild(build.id)
    await db_session.commit()

    snapshot = await get_project_graph_snapshot(db_session, tenant_id=tenant_id, project_id=project.id)
    assert set(snapshot["aiCardsByCenter"].keys()) == {"risk:alpha", "doc:beta"}
    assert set(calls) == {"risk:alpha", "doc:beta"}  # both enriched on the full rebuild

    calls.clear()

    # Only node A changes.
    node_a.name = "Risk Alpha Renamed"
    await db_session.flush()
    await db_session.commit()

    inc_build, build_type = await manager.request_incremental_rebuild(
        project.id,
        change_set=[
            {"entity_type": "risk", "entity_id": node_a.id, "action": "updated", "change_scope": "local"}
        ],
        requested_by=user_id,
    )
    await db_session.commit()
    assert build_type == "incremental"

    await manager.run_incremental_rebuild(inc_build.id)
    await db_session.commit()

    # Only the changed centre's card was re-enriched -- not the untouched one.
    assert calls == ["risk:alpha"]

    new_snapshot = await get_project_graph_snapshot(
        db_session, tenant_id=tenant_id, project_id=project.id,
    )
    assert set(new_snapshot["aiCardsByCenter"].keys()) == {"risk:alpha", "doc:beta"}
