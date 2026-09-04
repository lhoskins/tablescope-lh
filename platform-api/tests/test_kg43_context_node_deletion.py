"""KG-43: incremental context-node patching must remove goal/metric/risk
nodes (and any edge touching them) once the underlying record is deleted or
deactivated, not just add/update the ones that are still active.

Run from `platform-api`: `pytest -q tests/test_kg43_context_node_deletion.py`.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.jwt import TokenClaims
from app.models import Project
from app.models.project_context.goals import ProjectGoal
from app.models.project_context.metrics import ProjectMetric
from app.models.project_context.risks import ProjectRisk
from app.services.knowledge_graph_lifecycle import KnowledgeGraphLifecycleManager

pytestmark = pytest.mark.anyio


def _manager(session: AsyncSession, tenant_id: int, user_id: int) -> KnowledgeGraphLifecycleManager:
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


def _empty_payload() -> dict:
    return {"fullGraph": {"nodes": [], "edges": []}}


async def test_deactivated_goal_is_removed_on_next_patch(db_session):
    tenant_id, user_id = 301, 1
    project = await _project(db_session, tenant_id, user_id, "kg43a")
    goal_keep = ProjectGoal(tenant_id=tenant_id, project_id=project.id, title="Keep this goal", active=True)
    goal_drop = ProjectGoal(tenant_id=tenant_id, project_id=project.id, title="Drop this goal", active=True)
    db_session.add_all([goal_keep, goal_drop])
    await db_session.flush()

    manager = _manager(db_session, tenant_id, user_id)
    payload = _empty_payload()
    await manager._patch_context_nodes(payload, project.id, ["goal"], [])
    node_ids = {n["id"] for n in payload["fullGraph"]["nodes"]}
    assert {f"goal:{goal_keep.id}", f"goal:{goal_drop.id}"} <= node_ids

    # The goal is deactivated (soft-deleted) between incremental patches.
    goal_drop.active = False
    await db_session.flush()

    await manager._patch_context_nodes(payload, project.id, ["goal"], [goal_drop.id])
    node_ids = {n["id"] for n in payload["fullGraph"]["nodes"]}
    assert f"goal:{goal_keep.id}" in node_ids
    assert f"goal:{goal_drop.id}" not in node_ids


async def test_hard_deleted_metric_is_removed_on_next_patch(db_session):
    tenant_id, user_id = 302, 1
    project = await _project(db_session, tenant_id, user_id, "kg43b")
    metric = ProjectMetric(tenant_id=tenant_id, project_id=project.id, name="Cycle time")
    db_session.add(metric)
    await db_session.flush()
    metric_id = metric.id

    manager = _manager(db_session, tenant_id, user_id)
    payload = _empty_payload()
    await manager._patch_context_nodes(payload, project.id, ["metric"], [])
    node_ids = {n["id"] for n in payload["fullGraph"]["nodes"]}
    assert f"metric:{metric_id}" in node_ids

    await db_session.delete(metric)
    await db_session.flush()

    await manager._patch_context_nodes(payload, project.id, ["metric"], [metric_id])
    node_ids = {n["id"] for n in payload["fullGraph"]["nodes"]}
    assert f"metric:{metric_id}" not in node_ids


async def test_deleting_a_risk_prunes_its_edges_too(db_session):
    tenant_id, user_id = 303, 1
    project = await _project(db_session, tenant_id, user_id, "kg43c")
    risk = ProjectRisk(tenant_id=tenant_id, project_id=project.id, title="Vendor risk")
    db_session.add(risk)
    await db_session.flush()
    risk_id = risk.id
    risk_key = f"risk:{risk_id}"

    manager = _manager(db_session, tenant_id, user_id)
    payload = _empty_payload()
    # A node from another source (e.g. the AI graph) has an edge to the risk.
    payload["fullGraph"]["nodes"].append({"id": "s:process:1", "node_type": "process", "name": "Onboarding"})
    payload["fullGraph"]["edges"].append(
        {"id": "e1", "from_node_id": "s:process:1", "to_node_id": risk_key, "relationship_type": "threatens"}
    )
    await manager._patch_context_nodes(payload, project.id, ["risk"], [])
    node_ids = {n["id"] for n in payload["fullGraph"]["nodes"]}
    assert risk_key in node_ids
    assert len(payload["fullGraph"]["edges"]) == 1

    await db_session.delete(risk)
    await db_session.flush()

    await manager._patch_context_nodes(payload, project.id, ["risk"], [risk_id])
    node_ids = {n["id"] for n in payload["fullGraph"]["nodes"]}
    assert risk_key not in node_ids
    # The edge that pointed at the now-deleted risk node is gone too, not a
    # dangling reference left in the copied snapshot.
    assert payload["fullGraph"]["edges"] == []
    assert "s:process:1" in node_ids  # unrelated node is untouched


async def test_patching_one_type_never_touches_another_types_nodes(db_session):
    tenant_id, user_id = 304, 1
    project = await _project(db_session, tenant_id, user_id, "kg43d")
    goal = ProjectGoal(tenant_id=tenant_id, project_id=project.id, title="Ship v2", active=True)
    db_session.add(goal)
    await db_session.flush()

    manager = _manager(db_session, tenant_id, user_id)
    payload = _empty_payload()
    await manager._patch_context_nodes(payload, project.id, ["goal"], [])

    # A risk node that exists in the payload but was never itself patched in
    # (e.g. from an earlier patch cycle) must survive a goal-only patch even
    # though it's no longer backed by a query in *this* call.
    payload["fullGraph"]["nodes"].append(
        {"id": "risk:999", "node_type": "risk", "name": "Legacy risk", "properties": {}}
    )

    await manager._patch_context_nodes(payload, project.id, ["goal"], [])
    node_ids = {n["id"] for n in payload["fullGraph"]["nodes"]}
    assert "risk:999" in node_ids
    assert f"goal:{goal.id}" in node_ids
