"""KG-48: every build must record a per-stage duration breakdown (plus
retry attempt and failure category) so an operator can identify the slow
or failing stage for any build ID without reading raw logs.

Run from `platform-api`: `pytest -q tests/test_kg48_stage_metrics.py`.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.jwt import TokenClaims
from app.models import AIProjectGraphEdge, AIProjectGraphNode, KnowledgeGraphBuild, Project
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


async def test_successful_full_rebuild_records_every_stage_duration(db_session):
    tenant_id, user_id = 701, 1
    project = await _project(db_session, tenant_id, user_id, "kg48a")
    manager = _manager(db_session, tenant_id, user_id)

    build, _ = await manager.request_full_rebuild(project.id)
    await db_session.commit()
    await db_session.refresh(build)

    await manager.run_full_rebuild(build.id)
    await db_session.commit()

    refreshed = await db_session.get(KnowledgeGraphBuild, build.id)
    assert refreshed.status == "succeeded"
    metrics = refreshed.stage_metrics
    assert metrics is not None
    durations = metrics["durations_ms"]

    # Every stage the pipeline actually walks through on a successful full
    # rebuild has a recorded (non-negative) duration.
    for stage in (
        "queued", "initializing", "fingerprinting", "loading_sources",
        "ai_enrichment", "validating", "activating",
    ):
        assert stage in durations, f"missing duration for stage {stage!r}: {durations}"
        assert durations[stage] >= 0

    assert metrics["retry_attempt"] == 0
    assert metrics["failure_category"] is None


async def test_validation_failure_records_failure_category_and_partial_durations(db_session):
    tenant_id, user_id = 702, 1
    project = await _project(db_session, tenant_id, user_id, "kg48b")

    # A materially under-connected candidate (>50% orphan ratio, well past
    # the minimum-nodes-to-judge gate) -- validation must reject it.
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

    refreshed = await db_session.get(KnowledgeGraphBuild, build.id)
    assert refreshed.status == "failed"
    metrics = refreshed.stage_metrics
    assert metrics is not None
    assert metrics["failure_category"] == "validation_failed"

    durations = metrics["durations_ms"]
    # The pipeline reached validation before failing -- those stages have
    # recorded durations, but activation (which never ran) does not.
    for stage in (
        "queued", "initializing", "fingerprinting", "loading_sources",
        "ai_enrichment", "validating",
    ):
        assert stage in durations
    assert "activating" not in durations
