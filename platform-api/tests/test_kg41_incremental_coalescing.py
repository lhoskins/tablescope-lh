"""KG-41: rapid successive change events must coalesce their impact into the
already-queued build, not silently discard everything but the first event.

Run from `platform-api`: `pytest -q tests/test_kg41_incremental_coalescing.py`.
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


async def _active_project(session: AsyncSession, tenant_id: int, user_id: int, slug: str) -> Project:
    project = Project(tenant_id=tenant_id, name=f"{slug} Project", owner_id=user_id, is_shared=False)
    session.add(project)
    await session.flush()
    manager = _manager(session, tenant_id, user_id)
    build, _ = await manager.request_full_rebuild(project.id)
    await session.commit()
    await session.refresh(build)
    await manager.run_full_rebuild(build.id)
    await session.commit()
    return project


async def test_second_change_event_merges_into_the_queued_build(db_session):
    tenant_id, user_id = 101, 1
    project = await _active_project(db_session, tenant_id, user_id, "kg41")
    manager = _manager(db_session, tenant_id, user_id)

    build1, type1 = await manager.request_incremental_rebuild(
        project.id,
        change_set=[
            {"entity_type": "document", "entity_id": 10, "action": "updated", "change_scope": "local"}
        ],
    )
    await db_session.commit()
    assert type1 == "incremental"

    build2, type2 = await manager.request_incremental_rebuild(
        project.id,
        change_set=[
            {"entity_type": "risk", "entity_id": 99, "action": "created", "change_scope": "local"}
        ],
    )
    await db_session.commit()

    # Same queued build -- the second event coalesced, it didn't stack a duplicate.
    assert build2.id == build1.id
    assert type2 == "incremental"

    refreshed = await db_session.get(KnowledgeGraphBuild, build1.id)
    summary = refreshed.affected_entity_summary
    assert set(summary["affected_types"]) == {"document", "risk"}
    assert 10 in summary["affected_ids"]
    assert 99 in summary["affected_ids"]


async def test_an_unsafe_second_event_escalates_the_queued_build_to_full(db_session):
    tenant_id, user_id = 102, 1
    project = await _active_project(db_session, tenant_id, user_id, "kg41b")
    manager = _manager(db_session, tenant_id, user_id)

    build1, type1 = await manager.request_incremental_rebuild(
        project.id,
        change_set=[
            {"entity_type": "goal", "entity_id": 1, "action": "updated", "change_scope": "local"}
        ],
    )
    await db_session.commit()
    assert type1 == "incremental"

    # A schema-scoped change always forces a full rebuild -- even though this
    # build was already safely queued as incremental, folding in an unsafe
    # event must escalate the whole coalesced build.
    build2, type2 = await manager.request_incremental_rebuild(
        project.id,
        change_set=[
            {"entity_type": "data_source", "entity_id": 5, "action": "updated", "change_scope": "schema"}
        ],
    )
    await db_session.commit()

    assert build2.id == build1.id
    assert type2 == "full"
    refreshed = await db_session.get(KnowledgeGraphBuild, build1.id)
    assert refreshed.build_type == "full"
    assert "goal" in refreshed.affected_entity_summary["affected_types"]
    assert "data_source" in refreshed.affected_entity_summary["affected_types"]


async def test_source_checkpoint_advances_to_the_latest_event(db_session):
    tenant_id, user_id = 103, 1
    project = await _active_project(db_session, tenant_id, user_id, "kg41c")
    manager = _manager(db_session, tenant_id, user_id)

    t1 = datetime.now(UTC) - timedelta(minutes=5)
    t2 = datetime.now(UTC)

    build1, _ = await manager.request_incremental_rebuild(
        project.id,
        change_set=[
            {"entity_type": "document", "entity_id": 1, "action": "updated", "change_scope": "local"}
        ],
        source_checkpoint=t1,
    )
    await db_session.commit()

    build2, _ = await manager.request_incremental_rebuild(
        project.id,
        change_set=[
            {"entity_type": "document", "entity_id": 2, "action": "updated", "change_scope": "local"}
        ],
        source_checkpoint=t2,
    )
    await db_session.commit()

    assert build2.id == build1.id
    refreshed = await db_session.get(KnowledgeGraphBuild, build1.id)
    assert refreshed.source_checkpoint["timestamp"] == t2.isoformat()


async def test_no_duplicate_build_is_created_for_the_coalesced_events(db_session):
    tenant_id, user_id = 104, 1
    project = await _active_project(db_session, tenant_id, user_id, "kg41d")
    manager = _manager(db_session, tenant_id, user_id)

    for i in range(3):
        await manager.request_incremental_rebuild(
            project.id,
            change_set=[
                {"entity_type": "document", "entity_id": i, "action": "updated", "change_scope": "local"}
            ],
        )
        await db_session.commit()

    from sqlalchemy import select

    builds = (
        await db_session.scalars(
            select(KnowledgeGraphBuild).where(
                KnowledgeGraphBuild.project_id == project.id,
                KnowledgeGraphBuild.status == "queued",
            )
        )
    ).all()
    assert len(builds) == 1
    assert set(builds[0].affected_entity_summary["affected_ids"]) == {0, 1, 2}
