"""Tests for knowledge graph full/incremental rebuild pipelines."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from arq.worker import Retry
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.jwt import TokenClaims
from app.models import (
    AIProjectGraphNode,
    KnowledgeGraphVersion,
    Project,
    ProjectGoal,
)
from app.models.project_intelligence_snapshot import ProjectIntelligenceSnapshot
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


# ── Phase 2: KG rebuild decouples from insight rebuild ─────────────────


def _bind_sessions(monkeypatch, db_engine):
    """Point worker-side SessionLocal factories at the test engine."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    import app.routes.home_intelligence as hir
    import app.tasks.workflows as workflows

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(workflows, "SessionLocal", factory)
    monkeypatch.setattr(hir, "SessionLocal", factory)


async def test_rebuild_knowledge_graph_enqueues_rebuilt_job(
    db_engine, db_session, monkeypatch
):
    import app.tasks.workflows as workflows

    _bind_sessions(monkeypatch, db_engine)

    project = await _project(db_session, 1, 1, "kg-rebuilt")
    db_session.add(
        AIProjectGraphNode(
            tenant_id=1,
            project_id=project.id,
            node_type="project",
            source_type="project",
            source_id=project.id,
            name=project.name,
            created_by=1,
        )
    )
    await db_session.flush()

    enqueued: list[tuple[int, int, int]] = []

    async def fake_kg_rebuilt_enqueue(
        *, tenant_id: int, project_id: int, build_id: int
    ) -> str:
        enqueued.append((tenant_id, project_id, build_id))
        return "kg-rebuilt-job"

    monkeypatch.setattr(
        workflows, "enqueue_knowledge_graph_rebuilt", fake_kg_rebuilt_enqueue
    )

    manager = _manager(db_session, 1, 1)
    build, _ = await manager.request_full_rebuild(project.id)
    await db_session.commit()

    result = await workflows.rebuild_knowledge_graph({}, build.id)
    assert result["status"] == "ok"
    assert enqueued == [(1, project.id, build.id)]


async def test_knowledge_graph_rebuilt_marks_stale_and_enqueues_insights(
    db_engine, db_session, monkeypatch
):
    import app.tasks.workflows as workflows
    from app.config import get_settings

    _bind_sessions(monkeypatch, db_engine)

    project = await _project(db_session, 1, 1, "kg-rebuilt2")
    snap = ProjectIntelligenceSnapshot(
        tenant_id=1,
        user_id=1,
        project_id=project.id,
        suite="project_insight",
        payload={},
        is_stale=False,
    )
    db_session.add(snap)
    await db_session.commit()

    monkeypatch.setattr(
        get_settings(), "business_insight_event_refresh_enabled", True
    )
    monkeypatch.setattr(
        get_settings(), "project_insight_event_rebuild_enabled", True
    )

    bi_enqueued: list[tuple[int, int]] = []

    async def fake_bi_enqueue(*, tenant_id: int, project_id: int) -> str:
        bi_enqueued.append((tenant_id, project_id))
        return "bi-job"

    monkeypatch.setattr(
        workflows, "enqueue_refresh_business_insight_result", fake_bi_enqueue
    )

    pi_enqueued: list[tuple[int, int]] = []

    async def fake_pi_enqueue(*, tenant_id: int, project_id: int) -> str:
        pi_enqueued.append((tenant_id, project_id))
        return "pi-job"

    monkeypatch.setattr(workflows, "enqueue_rebuild_project_insight", fake_pi_enqueue)

    result = await workflows.knowledge_graph_rebuilt({}, 1, project.id, build_id=999)
    assert result["status"] == "ok"

    await db_session.refresh(snap)
    assert snap.is_stale is True
    assert bi_enqueued == [(1, project.id)]
    assert pi_enqueued == [(1, project.id)]


async def test_source_checkpoint_retries_until_rows_visible(db_session):
    """A build whose source checkpoint is newer than the visible staging rows must defer."""
    tenant_id = 1
    user_id = 1
    project = await _project(db_session, tenant_id, user_id, "checkpoint")

    manager = _manager(db_session, tenant_id, user_id)
    build, _ = await manager.request_full_rebuild(project.id, trigger="test")
    future = datetime.now(UTC) + timedelta(seconds=5)
    build.source_checkpoint = {"timestamp": future.isoformat()}
    await db_session.commit()

    with pytest.raises(Retry):
        await manager.run_full_rebuild(build.id)

    # The write "lands" after the retry. Provide a row whose created_at is
    # strictly >= the checkpoint so the next attempt proceeds.
    db_session.add(
        AIProjectGraphNode(
            tenant_id=tenant_id,
            project_id=project.id,
            node_type="project",
            source_type="project",
            source_id=project.id,
            name=project.name,
            created_by=user_id,
            created_at=future + timedelta(seconds=1),
        )
    )
    await db_session.commit()

    await manager.run_full_rebuild(build.id)
    await db_session.commit()

    graph = await manager.ensure_graph(project.id)
    assert graph.active_version_id is not None
