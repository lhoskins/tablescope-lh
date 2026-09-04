"""KG-21/22/23/47: activation validation must actually block a structurally
broken candidate, not just warn about it and activate it anyway.

Run from ``platform-api``: ``pytest -q tests/test_kg21_activation_validation.py``.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.jwt import TokenClaims
from app.models import AIProjectGraphEdge, AIProjectGraphNode, KnowledgeGraphBuild, Project
from app.services.knowledge_graph_lifecycle import KnowledgeGraphLifecycleManager
from app.services.knowledge_graph_lifecycle.structural_integrity import (
    evaluate_structural_integrity,
)

pytestmark = pytest.mark.anyio


def _manager(session: AsyncSession, tenant_id: int, user_id: int):
    return KnowledgeGraphLifecycleManager(
        session,
        RequestContext(
            claims=TokenClaims(sub=str(user_id), tenant_id=tenant_id, user_id=user_id, role="editor")
        ),
    )


async def _project(session: AsyncSession, tenant_id: int, user_id: int, slug: str) -> Project:
    project = Project(tenant_id=tenant_id, name=f"{slug} Project", owner_id=user_id, is_shared=False)
    session.add(project)
    await session.flush()
    return project


# ── Unit-level: evaluate_structural_integrity itself ──────────────────────

def _node(nid, ntype="document"):
    return {"id": nid, "node_type": ntype}


def _edge(a, b):
    return {"from_node_id": a, "to_node_id": b}


def test_dangling_edge_is_blocking_not_a_warning():
    nodes = [_node("project", "project"), _node(1)]
    edges = [_edge("project", 999)]  # 999 doesn't exist
    result = evaluate_structural_integrity(nodes, edges)
    assert result["valid"] is False
    assert any("missing nodes" in e for e in result["errors"])


def test_missing_project_hub_is_blocking():
    nodes = [_node(1), _node(2)]
    edges = [_edge(1, 2)]
    result = evaluate_structural_integrity(nodes, edges)
    assert result["valid"] is False
    assert any("project hub" in e for e in result["errors"])


def test_high_orphan_ratio_blocks_once_there_is_enough_coverage_to_judge():
    # 8 nodes, only 2 connected -- 75% orphan ratio, well past the threshold.
    nodes = [_node("project", "project")] + [_node(i) for i in range(1, 8)]
    edges = [_edge("project", 1)]
    result = evaluate_structural_integrity(nodes, edges)
    assert result["valid"] is False
    assert any("orphan ratio" in e.lower() for e in result["errors"])


def test_high_orphan_ratio_is_only_a_warning_for_a_tiny_new_project():
    # A brand-new project with just the hub -- 100% orphan ratio, but too
    # little source coverage to reject outright. Use a realistic (non
    # "project"-literal) id so the hub isn't coincidentally excluded from
    # orphan counting by the legacy `- {"project"}` id-string idiom.
    nodes = [_node("s:project:1", "project")]
    result = evaluate_structural_integrity(nodes, [])
    assert result["valid"] is True
    assert any("orphan" in w.lower() for w in result["warnings"])


def test_disconnected_components_is_actually_computed_not_a_stale_zero():
    # Two real multi-node clusters, both connected to the hub separately --
    # this is what a stored-but-never-computed field used to hide entirely.
    nodes = [_node("project", "project"), _node(1), _node(2), _node(3), _node(4)]
    edges = [_edge("project", 1), _edge(2, 3)]  # {project,1} and {2,3} -- 4 isolated
    result = evaluate_structural_integrity(nodes, edges)
    # {project,1} is the main component; {2,3} is one disconnected component.
    assert result["disconnected_components"] == 1


def test_isolated_singleton_nodes_are_orphans_not_disconnected_components():
    nodes = [_node("project", "project"), _node(1), _node(2)]
    edges = [_edge("project", 1)]  # node 2 has no edge at all
    result = evaluate_structural_integrity(nodes, edges)
    assert result["disconnected_components"] == 0
    assert result["isolated_node_count"] == 1


# ── Integration: a broken candidate must not replace the last healthy version ──
#
# Note: a full rebuild's payload always goes through merge_graph_sources
# (loader.py), which already drops any edge whose endpoint isn't a node in
# the same merged payload, and collect_structural_graph always contributes
# exactly one project-type hub node -- so a dangling edge or a missing
# project hub can't actually reach _validate_payload through this pipeline
# (the dangling-edge and missing-hub blocking behavior is proven at the
# evaluate_structural_integrity unit level above; it's real defense-in-depth
# for payloads assembled another way, e.g. a future incremental-patch bug --
# see item #43). A materially high orphan ratio, however, *is* reachable
# through the real pipeline, since it depends on actual project content.

async def test_a_materially_under_connected_candidate_never_gets_activated(db_session):
    tenant_id, user_id = 1, 1
    project = await _project(db_session, tenant_id, user_id, "kg21")

    # One connected pair, plus several isolated risk nodes with no edges at
    # all -- 8 total nodes, >50% orphaned, well past _MIN_NODES_FOR_ORPHAN_GATE.
    hub = AIProjectGraphNode(
        tenant_id=tenant_id, project_id=project.id, node_type="project",
        source_type="project", source_id=project.id, name=project.name,
        created_by=user_id, is_active=True,
    )
    linked = AIProjectGraphNode(
        tenant_id=tenant_id, project_id=project.id, node_type="risk",
        name="Linked risk", created_by=user_id, is_active=True,
    )
    db_session.add_all([hub, linked])
    await db_session.flush()
    db_session.add(
        AIProjectGraphEdge(
            tenant_id=tenant_id, project_id=project.id,
            from_node_id=hub.id, to_node_id=linked.id,
            relationship_type="contains", confidence=0.9, created_by=user_id,
            is_active=True,
        )
    )
    db_session.add_all([
        AIProjectGraphNode(
            tenant_id=tenant_id, project_id=project.id, node_type="risk",
            name=f"Orphan risk {i}", created_by=user_id, is_active=True,
        )
        for i in range(6)
    ])
    await db_session.flush()

    manager = _manager(db_session, tenant_id, user_id)
    build, _ = await manager.request_full_rebuild(project.id)
    await db_session.commit()
    await db_session.refresh(build)

    await manager.run_full_rebuild(build.id)
    await db_session.commit()

    graph = await manager.ensure_graph(project.id)
    assert graph.active_version_id is None
    refreshed_build = await db_session.get(KnowledgeGraphBuild, build.id)
    assert refreshed_build.status == "failed"
