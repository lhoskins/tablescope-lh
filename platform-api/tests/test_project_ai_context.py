"""Tests for the bounded project AI context builder."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.project_context import (
    ProjectBusinessContext,
    ProjectGoal,
    ProjectMetric,
    ProjectRisk,
)
from app.services.project_ai_context import (
    ProjectAIContextCache,
    build_project_ai_context,
    invalidate_project_ai_context,
)

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _reset_ai_context_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate the project AI context cache between tests."""
    from app.services import project_ai_context as pac

    monkeypatch.setattr(pac, "_context_cache", pac.ProjectAIContextCache())


async def _scaffold(session: AsyncSession):
    project = Project(tenant_id=1, name="AI Context Project", owner_id=1)
    session.add(project)
    await session.flush()

    settings = ProjectBusinessContext(
        tenant_id=1,
        project_id=project.id,
        ai_context_enabled=True,
        ai_instructions="Compare to budget",
        interpretation_notes="Use monthly view",
    )
    session.add(settings)
    await session.flush()

    goal = ProjectGoal(
        tenant_id=1,
        project_id=project.id,
        title="Reduce costs",
        priority="high",
        status="in_progress",
        position=1,
    )
    metric = ProjectMetric(
        tenant_id=1,
        project_id=project.id,
        name="Total spend",
        directionality="lower_is_better",
        aggregation="sum",
        position=1,
    )
    risk = ProjectRisk(
        tenant_id=1,
        project_id=project.id,
        title="Budget overrun",
        likelihood="possible",
        impact="major",
        severity="high",
        status="open",
        position=1,
    )
    session.add_all([goal, metric, risk])
    await session.flush()
    return project, settings


async def test_build_ai_context_returns_structured_package(db_session: AsyncSession):
    project, _ = await _scaffold(db_session)
    package = await build_project_ai_context(
        db_session,
        tenant_id=1,
        project_id=project.id,
        request_type="test",
        token_budget=2000,
    )
    assert package["ai_context_enabled"] is True
    assert package["project"]["name"] == "AI Context Project"
    assert any(g["title"] == "Reduce costs" for g in package["goals"])
    assert any(m["name"] == "Total spend" for m in package["metrics"])
    assert any(r["title"] == "Budget overrun" for r in package["risks"])
    assert package["instructions"] == "Compare to budget"
    assert package["token_budget"] == 2000
    assert package["estimated_tokens"] > 0


async def test_build_ai_context_disabled_returns_minimal_package(db_session: AsyncSession):
    project, settings = await _scaffold(db_session)
    settings.ai_context_enabled = False
    settings.version += 1
    await db_session.flush()

    package = await build_project_ai_context(
        db_session,
        tenant_id=1,
        project_id=project.id,
        request_type="test",
    )
    assert package["ai_context_enabled"] is False
    assert package["goals"] == []
    assert package["metrics"] == []
    assert package["risks"] == []


async def test_build_ai_context_caches_by_version(db_session: AsyncSession):
    project, settings = await _scaffold(db_session)
    cache = ProjectAIContextCache()

    package1 = await build_project_ai_context(
        db_session,
        tenant_id=1,
        project_id=project.id,
        request_type="test",
        cache=cache,
    )
    package2 = await build_project_ai_context(
        db_session,
        tenant_id=1,
        project_id=project.id,
        request_type="test",
        cache=cache,
    )
    assert package1 is package2

    settings.ai_instructions = "Updated"
    settings.version += 1
    await db_session.flush()

    package3 = await build_project_ai_context(
        db_session,
        tenant_id=1,
        project_id=project.id,
        request_type="test",
        cache=cache,
    )
    assert package3 is not package1


async def test_invalidate_project_ai_context_clears_cache():
    from app.services.project_ai_context import _context_cache

    _context_cache.set(1, 1, 0, {"payload": "x"})
    assert _context_cache.get(1, 1, 0) is not None
    invalidate_project_ai_context(1, 1)
    assert _context_cache.get(1, 1, 0) is None


async def test_build_ai_context_tenant_isolation(db_session: AsyncSession):
    project, _ = await _scaffold(db_session)
    package = await build_project_ai_context(
        db_session,
        tenant_id=2,
        project_id=project.id,
        request_type="test",
    )
    # With tenant_id mismatch the builder returns an error package.
    assert package.get("error") == "Project not found"
