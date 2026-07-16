"""Tests for knowledge graph full/incremental rebuild pipelines."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.jwt import TokenClaims
from app.models import (
    AIProjectGraphNode,
    KnowledgeGraphVersion,
    Project,
    ProjectGoal,
)
from app.services.knowledge_graph_lifecycle import KnowledgeGraphLifecycleManager

pytestmark = pytest.mark.anyio


def _manager(session: AsyncSession, tenant_id: int, user_id: int, role: str = "editor"):
    return KnowledgeGraphLifecycleManager(
        session,
        RequestContext(
            claims=TokenClaims(
                sub=str(user_id), tenant_id=tenant_id, user_id=user_id, role=role
            )
        ),
    )


async def _project(session: AsyncSession, tenant_id: int, user_id: int, slug: str):
    project = Project(
        tenant_id=tenant_id,
        name=f"{slug} Project",
        owner_id=user_id,
        is_shared=False,
    )
    session.add(project)
    await session.flush()
    return project


async def test_full_rebuild_creates_and_activates_version(db_session):
    tenant_id = 1
    user_id = 1
    project = await _project(db_session, tenant_id, user_id, "rebuild")

    # Seed a minimal graph so validation passes.
    node = AIProjectGraphNode(
        tenant_id=tenant_id,
        project_id=project.id,
        node_type="project",
        source_type="project",
        source_id=project.id,
        name=project.name,
        created_by=user_id,
    )
    db_session.add(node)
    await db_session.flush()

    manager = _manager(db_session, tenant_id, user_id)
    build, _ = await manager.request_full_rebuild(project.id)
    await db_session.commit()

    # Refresh to get an independent transaction view.
    await db_session.refresh(build)

    await manager.run_full_rebuild(build.id)
    await db_session.commit()

    graph = await manager.ensure_graph(project.id)
    assert graph.lifecycle_status == "active"
    assert graph.active_version_id is not None

    version = await db_session.get(KnowledgeGraphVersion, graph.active_version_id)
    assert version is not None
    assert version.status == "active"
    assert version.storage_reference is not None
    assert version.node_count >= 1


async def test_incremental_rebuild_patches_context_nodes(db_session):
    tenant_id = 1
    user_id = 1
    project = await _project(db_session, tenant_id, user_id, "incremental")

    # Seed an active graph with a project hub.
    node = AIProjectGraphNode(
        tenant_id=tenant_id,
        project_id=project.id,
        node_type="project",
        source_type="project",
        source_id=project.id,
        name=project.name,
        created_by=user_id,
    )
    db_session.add(node)
    goal = ProjectGoal(
        tenant_id=tenant_id,
        project_id=project.id,
        title="Improve quality",
        priority="high",
        status="active",
        active=True,
        position=0,
    )
    db_session.add(goal)
    await db_session.flush()

    manager = _manager(db_session, tenant_id, user_id)
    full_build, _ = await manager.request_full_rebuild(project.id)
    await manager.run_full_rebuild(full_build.id)
    await db_session.commit()

    # Request an incremental rebuild for the new goal.
    inc_build, _ = await manager.request_incremental_rebuild(
        project.id,
        change_set=[
            {
                "entity_type": "goal",
                "entity_id": goal.id,
                "action": "added",
                "change_scope": "local",
            }
        ],
    )
    await db_session.commit()
    await manager.run_incremental_rebuild(inc_build.id)
    await db_session.commit()

    graph = await manager.ensure_graph(project.id)
    assert graph.lifecycle_status == "active"
    active = await db_session.get(KnowledgeGraphVersion, graph.active_version_id)
    assert active is not None
    assert active.build_type == "incremental"


async def test_incremental_falls_back_to_full_without_active_version(db_session):
    tenant_id = 1
    user_id = 1
    project = await _project(db_session, tenant_id, user_id, "fallback")

    node = AIProjectGraphNode(
        tenant_id=tenant_id,
        project_id=project.id,
        node_type="project",
        source_type="project",
        source_id=project.id,
        name=project.name,
        created_by=user_id,
    )
    db_session.add(node)
    await db_session.flush()

    manager = _manager(db_session, tenant_id, user_id)
    # Create a build record marked incremental but with no active version.
    inc_build, _ = await manager.request_incremental_rebuild(
        project.id,
        change_set=[
            {
                "entity_type": "goal",
                "entity_id": 1,
                "action": "updated",
                "change_scope": "local",
            }
        ],
    )
    await db_session.commit()
    await manager.run_incremental_rebuild(inc_build.id)
    await db_session.commit()

    graph = await manager.ensure_graph(project.id)
    assert graph.lifecycle_status == "active"
    assert graph.active_version_id is not None
