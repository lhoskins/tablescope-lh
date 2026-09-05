"""KG-46: stale-build recovery must not depend on a non-null heartbeat.

``heartbeat_at < cutoff`` never matches a NULL heartbeat in SQL, so a build
that was queued but never picked up by a worker (lost queue message, worker
crash before dequeue) was invisible to recovery forever. Builds now get a
heartbeat at queue time, and recovery also falls back to ``queued_at`` then
``created_at`` for any build that still ends up with a null one.

Run from `platform-api`: `pytest -q tests/test_kg46_heartbeat_recovery.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.jwt import TokenClaims
from app.models import KnowledgeGraphBuild, Project
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


async def test_request_full_rebuild_sets_an_initial_heartbeat(db_session):
    tenant_id, user_id = 601, 1
    project = await _project(db_session, tenant_id, user_id, "kg46a")
    manager = _manager(db_session, tenant_id, user_id)

    build, _ = await manager.request_full_rebuild(project.id)
    assert build.heartbeat_at is not None


async def test_request_incremental_rebuild_sets_an_initial_heartbeat(db_session):
    tenant_id, user_id = 602, 1
    project = await _project(db_session, tenant_id, user_id, "kg46b")
    manager = _manager(db_session, tenant_id, user_id)
    graph = await manager.ensure_graph(project.id)
    graph.lifecycle_status = "active"
    await db_session.flush()

    build, _ = await manager.request_incremental_rebuild(
        project.id,
        change_set=[
            {"entity_type": "document", "entity_id": 1, "action": "updated", "change_scope": "local"}
        ],
    )
    assert build.heartbeat_at is not None


async def test_recover_stale_builds_catches_a_null_heartbeat_via_queued_at(db_session):
    tenant_id, user_id = 603, 1
    project = await _project(db_session, tenant_id, user_id, "kg46c")
    manager = _manager(db_session, tenant_id, user_id)
    graph = await manager.ensure_graph(project.id)

    # Simulates a build that was queued (e.g. by code predating this fix, or
    # a future code path that forgets to set the heartbeat) but never picked
    # up by any worker -- heartbeat_at stays NULL forever.
    old_queued_at = datetime.now(UTC) - timedelta(seconds=1000)
    build = KnowledgeGraphBuild(
        graph_id=graph.id, tenant_id=tenant_id, project_id=project.id,
        trigger_type="manual", build_type="full", status="queued",
        queued_at=old_queued_at, heartbeat_at=None,
    )
    db_session.add(build)
    await db_session.flush()

    recovered = await manager.recover_stale_builds()

    assert build.id in recovered
    refreshed = await db_session.get(KnowledgeGraphBuild, build.id)
    assert refreshed.status == "failed"
    assert refreshed.error_code == "stale_recovery"


async def test_recover_stale_builds_still_catches_a_stale_heartbeat(db_session):
    tenant_id, user_id = 604, 1
    project = await _project(db_session, tenant_id, user_id, "kg46d")
    manager = _manager(db_session, tenant_id, user_id)
    graph = await manager.ensure_graph(project.id)

    stale_ts = datetime.now(UTC) - timedelta(seconds=1000)
    build = KnowledgeGraphBuild(
        graph_id=graph.id, tenant_id=tenant_id, project_id=project.id,
        trigger_type="manual", build_type="full", status="building",
        queued_at=stale_ts, heartbeat_at=stale_ts,
    )
    db_session.add(build)
    await db_session.flush()

    recovered = await manager.recover_stale_builds()
    assert build.id in recovered


async def test_recover_stale_builds_leaves_a_fresh_build_alone(db_session):
    tenant_id, user_id = 605, 1
    project = await _project(db_session, tenant_id, user_id, "kg46e")
    manager = _manager(db_session, tenant_id, user_id)

    build, _ = await manager.request_full_rebuild(project.id)
    await db_session.flush()

    recovered = await manager.recover_stale_builds()
    assert build.id not in recovered
