"""KG-44: source-checkpoint verification must watch every graph-relevant
source, not just the AI staging node/edge tables -- a content *update*
never bumps those tables' created_at (no updated_at column), and a change
to any non-staging source (goal/metric/risk edit, file/query/dashboard
rename, reference-library update, repository scan) was never watched at
all, so a coalesced build could start before such a change was visible.

Run from `platform-api`: `pytest -q tests/test_kg44_source_checkpoint_watermark.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from arq.worker import Retry
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.jwt import TokenClaims
from app.models import KnowledgeGraphBuild, Project
from app.models.project_context.goals import ProjectGoal
from app.models.project_context.metrics import ProjectMetric
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


async def test_current_source_watermark_is_none_with_no_sources(db_session):
    tenant_id, user_id = 401, 1
    project = await _project(db_session, tenant_id, user_id, "kg44a")
    manager = _manager(db_session, tenant_id, user_id)
    assert await manager.current_source_watermark(project.id, tenant_id) is None


async def test_current_source_watermark_reflects_a_non_staging_source(db_session):
    tenant_id, user_id = 402, 1
    project = await _project(db_session, tenant_id, user_id, "kg44b")
    manager = _manager(db_session, tenant_id, user_id)

    metric = ProjectMetric(tenant_id=tenant_id, project_id=project.id, name="Cycle time")
    db_session.add(metric)
    await db_session.flush()

    watermark = await manager.current_source_watermark(project.id, tenant_id)
    assert watermark is not None


async def test_verify_source_checkpoint_sees_a_goal_update_the_old_watermark_missed(db_session):
    tenant_id, user_id = 403, 1
    project = await _project(db_session, tenant_id, user_id, "kg44c")
    manager = _manager(db_session, tenant_id, user_id)
    graph = await manager.ensure_graph(project.id)

    # A checkpoint set ahead of "now" -- nothing in the AI staging tables
    # will ever satisfy it, but a non-staging source (a goal) was updated
    # at/after the checkpoint moment.
    checkpoint_ts = datetime.now(UTC) + timedelta(hours=1)
    goal = ProjectGoal(
        tenant_id=tenant_id, project_id=project.id, title="Ship v2",
        updated_at=checkpoint_ts + timedelta(seconds=1),
    )
    db_session.add(goal)
    await db_session.flush()

    build = KnowledgeGraphBuild(
        graph_id=graph.id, tenant_id=tenant_id, project_id=project.id,
        trigger_type="change_event", build_type="incremental", status="queued",
        source_checkpoint={"timestamp": checkpoint_ts.isoformat()},
    )
    db_session.add(build)
    await db_session.flush()

    # Must not raise Retry -- the broadened watermark sees the goal update
    # even though no AIProjectGraphNode/Edge row was ever touched.
    await manager._verify_source_checkpoint(build)


async def test_verify_source_checkpoint_still_defers_when_nothing_is_visible(db_session):
    tenant_id, user_id = 404, 1
    project = await _project(db_session, tenant_id, user_id, "kg44d")
    manager = _manager(db_session, tenant_id, user_id)
    graph = await manager.ensure_graph(project.id)

    checkpoint_ts = datetime.now(UTC) + timedelta(hours=1)
    build = KnowledgeGraphBuild(
        graph_id=graph.id, tenant_id=tenant_id, project_id=project.id,
        trigger_type="change_event", build_type="incremental", status="queued",
        source_checkpoint={"timestamp": checkpoint_ts.isoformat()},
    )
    db_session.add(build)
    await db_session.flush()

    with pytest.raises(Retry):
        await manager._verify_source_checkpoint(build)
