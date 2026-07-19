"""Tests for the tenant-shared per-project Business Insight result cache.

Phase 2 of the Business Insights plan: cards are cached once per
(tenant, project, granularity), keyed to the active Knowledge Graph version,
served to every user who passes the project access check, and refreshed in the
background after a successful KG build (activity-gated).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.models import (
    AIProjectGraphNode,
    BusinessInsightResult,
    IntelligenceSnapshot,
    KnowledgeGraph,
    Project,
)
from app.services import business_insight_cache as bi_cache

pytestmark = pytest.mark.anyio

CARDS = [{"insightId": "c1", "title": "Margin dip", "insightType": "risk"}]


async def _project(session: AsyncSession, tenant_id: int, owner_id: int, slug: str):
    project = Project(
        tenant_id=tenant_id,
        name=f"{slug} Project",
        owner_id=owner_id,
        is_shared=False,
    )
    session.add(project)
    await session.flush()
    return project


def _bind_sessions(monkeypatch, db_engine):
    """Point both worker-side SessionLocal factories at the test engine."""
    import app.routes.home_intelligence as hir
    import app.tasks.workflows as workflows

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(workflows, "SessionLocal", factory)
    monkeypatch.setattr(hir, "SessionLocal", factory)


def _patch_queue(monkeypatch):
    """Fake the Redis-backed run-queue helpers used by the worker tasks."""
    import app.services.home_intel_queue as q
    import app.tasks.workflows as workflows

    written: dict[str, dict] = {}

    async def _true(*args, **kwargs):
        return True

    async def _none(*args, **kwargs):
        return None

    async def write_result(run_id, project_id, result):
        written[str(project_id)] = result

    monkeypatch.setattr(q, "is_current_run", _true)
    monkeypatch.setattr(q, "acquire_tenant_slot", _true)
    monkeypatch.setattr(q, "release_tenant_slot", _none)
    monkeypatch.setattr(q, "write_result", write_result)
    monkeypatch.setattr(workflows, "_finalize_run_if_complete", _none)
    return written


# ── Cache service ────────────────────────────────────────────────────


async def test_cache_roundtrip_and_invalidation(db_session):
    project = await _project(db_session, 1, 1, "cache")

    await bi_cache.store_result(
        db_session,
        tenant_id=1,
        project_id=project.id,
        granularity=3,
        cards=CARDS,
        built_by=1,
    )
    fresh = await bi_cache.get_fresh_result(
        db_session, tenant_id=1, project_id=project.id, granularity=3
    )
    assert fresh == CARDS

    # A different granularity is a different cache entry.
    assert (
        await bi_cache.get_fresh_result(
            db_session, tenant_id=1, project_id=project.id, granularity=5
        )
        is None
    )

    # KG version drift invalidates: activate a version the row wasn't built on.
    graph = KnowledgeGraph(
        tenant_id=1,
        project_id=project.id,
        lifecycle_status="active",
        enabled=True,
        version=1,
        active_version_id=12345,
    )
    db_session.add(graph)
    await db_session.commit()
    assert (
        await bi_cache.get_fresh_result(
            db_session, tenant_id=1, project_id=project.id, granularity=3
        )
        is None
    )


async def test_cache_ttl_expiry(db_session, monkeypatch):
    project = await _project(db_session, 1, 1, "ttl")
    await bi_cache.store_result(
        db_session,
        tenant_id=1,
        project_id=project.id,
        granularity=3,
        cards=CARDS,
        built_by=1,
    )
    row = await db_session.scalar(select(BusinessInsightResult))
    row.updated_at = datetime.now(UTC) - timedelta(days=3)
    await db_session.commit()

    assert (
        await bi_cache.get_fresh_result(
            db_session, tenant_id=1, project_id=project.id, granularity=3
        )
        is None
    )


async def test_cache_rejects_rows_from_older_analysis_pipeline(db_session):
    """Cards cached before an ANALYSIS_VERSION bump must miss, not serve.

    This is how a planner-quality fix (e.g. the multi-table regression fix)
    propagates through the shared cache immediately instead of pinning
    degraded cards until KG drift or TTL expiry.
    """
    project = await _project(db_session, 1, 1, "version-gate")
    await bi_cache.store_result(
        db_session,
        tenant_id=1,
        project_id=project.id,
        granularity=3,
        cards=CARDS,
        built_by=1,
    )
    row = await db_session.scalar(select(BusinessInsightResult))
    # Simulate a row written by the previous pipeline version.
    row.payload = {"insights": CARDS, "analysis_version": bi_cache.ANALYSIS_VERSION - 1}
    await db_session.commit()

    assert (
        await bi_cache.get_fresh_result(
            db_session, tenant_id=1, project_id=project.id, granularity=3
        )
        is None
    )


# ── Cache-aware analyze_project_intelligence ─────────────────────────


async def test_analyze_serves_from_cache_without_running_analysis(
    db_engine, db_session, monkeypatch
):
    import app.routes.home_intelligence as hir
    import app.tasks.workflows as workflows

    _bind_sessions(monkeypatch, db_engine)
    written = _patch_queue(monkeypatch)
    monkeypatch.setattr(get_settings(), "business_insight_shared_cache_enabled", True)

    project = await _project(db_session, 1, 1, "hit")
    await bi_cache.store_result(
        db_session,
        tenant_id=1,
        project_id=project.id,
        granularity=3,
        cards=CARDS,
        built_by=1,
    )

    async def _has_access(*args, **kwargs):
        return True

    async def _must_not_run(*args, **kwargs):
        raise AssertionError("analysis ran despite a fresh cache entry")

    monkeypatch.setattr(hir, "_has_access", _has_access)
    monkeypatch.setattr(hir, "_run_for_project", _must_not_run)

    result = await workflows.analyze_project_intelligence(
        {"job_try": 1},
        tenant_id=1,
        user_id=2,  # a different user than built_by: results are shared
        project_id=project.id,
        granularity=3,
        run_id="run-1",
    )

    assert result["insights"] == CARDS
    assert result["fromCache"] is True
    assert written[str(project.id)]["insights"] == CARDS


async def test_analyze_runs_and_stores_on_cache_miss(
    db_engine, db_session, monkeypatch
):
    import app.routes.home_intelligence as hir
    import app.tasks.workflows as workflows

    _bind_sessions(monkeypatch, db_engine)
    _patch_queue(monkeypatch)
    monkeypatch.setattr(get_settings(), "business_insight_shared_cache_enabled", True)

    project = await _project(db_session, 1, 1, "miss")
    await db_session.commit()

    async def _has_access(*args, **kwargs):
        return True

    async def _run(*args, **kwargs):
        return CARDS

    monkeypatch.setattr(hir, "_has_access", _has_access)
    monkeypatch.setattr(hir, "_run_for_project", _run)

    result = await workflows.analyze_project_intelligence(
        {"job_try": 1},
        tenant_id=1,
        user_id=1,
        project_id=project.id,
        granularity=3,
        run_id="run-2",
    )
    assert result["insights"] == CARDS

    row = await db_session.scalar(
        select(BusinessInsightResult).where(
            BusinessInsightResult.project_id == project.id
        )
    )
    assert row is not None
    assert row.payload["insights"] == CARDS
    assert row.built_by == 1


async def test_analyze_ignores_cache_when_flag_disabled(
    db_engine, db_session, monkeypatch
):
    import app.routes.home_intelligence as hir
    import app.tasks.workflows as workflows

    _bind_sessions(monkeypatch, db_engine)
    _patch_queue(monkeypatch)
    monkeypatch.setattr(get_settings(), "business_insight_shared_cache_enabled", False)

    project = await _project(db_session, 1, 1, "flag-off")
    await bi_cache.store_result(
        db_session,
        tenant_id=1,
        project_id=project.id,
        granularity=3,
        cards=[{"insightId": "stale"}],
        built_by=1,
    )

    ran: list[bool] = []

    async def _has_access(*args, **kwargs):
        return True

    async def _run(*args, **kwargs):
        ran.append(True)
        return CARDS

    monkeypatch.setattr(hir, "_has_access", _has_access)
    monkeypatch.setattr(hir, "_run_for_project", _run)

    result = await workflows.analyze_project_intelligence(
        {"job_try": 1},
        tenant_id=1,
        user_id=1,
        project_id=project.id,
        granularity=3,
        run_id="run-3",
    )
    assert ran == [True]
    assert result["insights"] == CARDS
    assert "fromCache" not in result


# ── Event-driven background refresh ──────────────────────────────────


async def test_refresh_disabled_flag_short_circuits(db_engine, monkeypatch):
    import app.tasks.workflows as workflows

    _bind_sessions(monkeypatch, db_engine)
    monkeypatch.setattr(
        get_settings(), "business_insight_event_refresh_enabled", False
    )
    result = await workflows.refresh_business_insight_result(
        {}, tenant_id=1, project_id=1
    )
    assert result["status"] == "disabled"


async def test_refresh_activity_gate_skips_idle_tenant(
    db_engine, db_session, monkeypatch
):
    import app.tasks.workflows as workflows

    _bind_sessions(monkeypatch, db_engine)
    monkeypatch.setattr(get_settings(), "business_insight_event_refresh_enabled", True)

    project = await _project(db_session, 1, 1, "idle")
    await db_session.commit()

    result = await workflows.refresh_business_insight_result(
        {}, tenant_id=1, project_id=project.id
    )
    assert result == {
        "status": "skipped",
        "reason": "no_recent_activity",
        "project_id": project.id,
    }


async def test_refresh_runs_as_owner_and_stores(db_engine, db_session, monkeypatch):
    import app.routes.home_intelligence as hir
    import app.tasks.workflows as workflows

    _bind_sessions(monkeypatch, db_engine)
    _patch_queue(monkeypatch)
    monkeypatch.setattr(get_settings(), "business_insight_event_refresh_enabled", True)

    project = await _project(db_session, 1, 7, "active")
    db_session.add(
        IntelligenceSnapshot(tenant_id=1, user_id=3, granularity=3, payload={})
    )
    await db_session.commit()

    seen: dict = {}

    async def _run(session, context, proj, prompt_types, **kwargs):
        seen["user_id"] = context.user_id
        seen["kwargs"] = kwargs
        return CARDS

    monkeypatch.setattr(hir, "_run_for_project", _run)

    result = await workflows.refresh_business_insight_result(
        {"job_try": 1}, tenant_id=1, project_id=project.id
    )
    assert result["status"] == "ok"
    assert result["card_count"] == len(CARDS)
    assert seen["user_id"] == 7  # project owner
    assert seen["kwargs"]["write_audit"] is False

    row = await db_session.scalar(
        select(BusinessInsightResult).where(
            BusinessInsightResult.project_id == project.id
        )
    )
    assert row is not None
    assert row.built_by == 7
    assert row.payload["insights"] == CARDS


async def test_kg_build_success_enqueues_refresh(db_engine, db_session, monkeypatch):
    import app.tasks.workflows as workflows
    from app.services.knowledge_graph_lifecycle import KnowledgeGraphLifecycleManager

    _bind_sessions(monkeypatch, db_engine)
    monkeypatch.setattr(get_settings(), "business_insight_event_refresh_enabled", True)

    enqueued: list[tuple[int, int]] = []

    async def fake_enqueue(*, tenant_id: int, project_id: int) -> str:
        enqueued.append((tenant_id, project_id))
        return "bi-job"

    monkeypatch.setattr(
        workflows, "enqueue_refresh_business_insight_result", fake_enqueue
    )

    project = await _project(db_session, 1, 1, "kg-chain")
    db_session.add(
        AIProjectGraphNode(
            tenant_id=1,
            project_id=project.id,
            node_type="project",
            source_type="project",
            source_id=project.id,
            name=project.name,
            created_by=1,
            is_active=True,
        )
    )
    await db_session.flush()

    manager = KnowledgeGraphLifecycleManager(db_session)
    build, _ = await manager.request_full_rebuild(project.id, requested_by=1)
    await db_session.commit()

    result = await workflows.rebuild_knowledge_graph({}, build.id)
    assert result["status"] == "ok"
    assert enqueued == [(1, project.id)]
