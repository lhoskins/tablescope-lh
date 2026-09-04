"""KG-45: durable idempotency and out-of-order-completion safety.

Two concerns:
- A redelivered/retried queue message for a build that already finished
  must not redo the work (duplicate version/snapshot, duplicate AI spend).
- An older, slower build finishing *after* a newer, faster build already
  activated its own version must not regress the active graph.

Run from `platform-api`: `pytest -q tests/test_kg45_idempotency_and_ordering.py`.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.jwt import TokenClaims
from app.models import (
    KnowledgeGraphBuild,
    KnowledgeGraphVersion,
    Project,
)
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


async def _version_count(session: AsyncSession, project_id: int) -> int:
    return await session.scalar(
        select(func.count())
        .select_from(KnowledgeGraphVersion)
        .where(KnowledgeGraphVersion.project_id == project_id)
    )


# ── activate_version: out-of-order completion ──────────────────────────────

async def test_activate_version_ignores_an_older_out_of_order_completion(db_session):
    tenant_id, user_id = 501, 1
    project = await _project(db_session, tenant_id, user_id, "kg45a")
    manager = _manager(db_session, tenant_id, user_id)
    graph = await manager.ensure_graph(project.id)

    v1 = KnowledgeGraphVersion(
        graph_id=graph.id, tenant_id=tenant_id, project_id=project.id,
        version_number=1, status="ready",
    )
    v2 = KnowledgeGraphVersion(
        graph_id=graph.id, tenant_id=tenant_id, project_id=project.id,
        version_number=2, status="ready",
    )
    db_session.add_all([v1, v2])
    await db_session.flush()

    # The newer build (v2) finishes and activates first.
    await manager.activate_version(graph.id, v2.id)
    assert graph.active_version_id == v2.id
    assert v2.status == "active"

    # The older build (v1), which had been running longer, finishes after
    # and tries to activate -- must not regress the active graph.
    await manager.activate_version(graph.id, v1.id)
    assert graph.active_version_id == v2.id
    assert v2.status == "active"


async def test_activate_version_still_activates_a_genuinely_newer_version(db_session):
    tenant_id, user_id = 502, 1
    project = await _project(db_session, tenant_id, user_id, "kg45b")
    manager = _manager(db_session, tenant_id, user_id)
    graph = await manager.ensure_graph(project.id)

    v1 = KnowledgeGraphVersion(
        graph_id=graph.id, tenant_id=tenant_id, project_id=project.id,
        version_number=1, status="ready",
    )
    v2 = KnowledgeGraphVersion(
        graph_id=graph.id, tenant_id=tenant_id, project_id=project.id,
        version_number=2, status="ready",
    )
    db_session.add_all([v1, v2])
    await db_session.flush()

    await manager.activate_version(graph.id, v1.id)
    assert graph.active_version_id == v1.id

    await manager.activate_version(graph.id, v2.id)
    assert graph.active_version_id == v2.id
    assert v1.status == "superseded"


# ── run_full_rebuild / run_incremental_rebuild: idempotent on redelivery ──

async def test_run_full_rebuild_skips_a_redelivered_already_succeeded_build(db_session):
    tenant_id, user_id = 503, 1
    project = await _project(db_session, tenant_id, user_id, "kg45c")
    manager = _manager(db_session, tenant_id, user_id)

    build, _ = await manager.request_full_rebuild(project.id, requested_by=user_id)
    await db_session.commit()
    await db_session.refresh(build)
    await manager.run_full_rebuild(build.id)
    await db_session.commit()
    await db_session.refresh(build)
    assert build.status == "succeeded"

    before = await _version_count(db_session, project.id)

    # A redelivered queue message for the same build_id.
    await manager.run_full_rebuild(build.id)
    await db_session.commit()

    after = await _version_count(db_session, project.id)
    assert after == before


async def test_run_incremental_rebuild_skips_an_already_failed_build(db_session):
    tenant_id, user_id = 504, 1
    project = await _project(db_session, tenant_id, user_id, "kg45d")
    manager = _manager(db_session, tenant_id, user_id)
    graph = await manager.ensure_graph(project.id)

    build = KnowledgeGraphBuild(
        graph_id=graph.id, tenant_id=tenant_id, project_id=project.id,
        trigger_type="change_event", build_type="incremental", status="failed",
    )
    db_session.add(build)
    await db_session.flush()

    before = await _version_count(db_session, project.id)
    await manager.run_incremental_rebuild(build.id)
    after = await _version_count(db_session, project.id)

    assert after == before
    refreshed = await db_session.get(KnowledgeGraphBuild, build.id)
    assert refreshed.status == "failed"
