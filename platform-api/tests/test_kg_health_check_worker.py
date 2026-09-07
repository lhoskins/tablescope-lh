"""TS-ISO-017 canary: run_knowledge_graph_health_check via tenant_session.

This worker job was the first migrated off a bare ``SessionLocal()`` onto
the existing (previously unadopted) ``tenant_session`` helper, which binds
Postgres RLS for the duration of the job. These tests confirm the job still
does real work (commits its health-check row) and still reports failures
the same way, now that ``tenant_id`` is threaded through the enqueue call
and the worker signature.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker

from app import database as database_module
from app.models import KnowledgeGraphHealthCheck, Project, ProjectBusinessContext
from app.tasks import workflows

pytestmark = pytest.mark.anyio


@pytest_asyncio.fixture
async def seeded_project(db_engine, monkeypatch):
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(database_module, "SessionLocal", session_factory)

    async with session_factory() as session:
        project = Project(
            tenant_id=1,
            name="Canary Project",
            owner_id=1,
            is_shared=False,
        )
        session.add(project)
        await session.flush()
        session.add(
            ProjectBusinessContext(
                tenant_id=1,
                project_id=project.id,
                ai_context_enabled=True,
                version=0,
            )
        )
        await session.commit()
        project_id = project.id

    return session_factory, project_id


async def test_health_check_worker_commits_via_tenant_session(seeded_project):
    session_factory, project_id = seeded_project

    result = await workflows.run_knowledge_graph_health_check(
        {}, tenant_id=1, project_id=project_id
    )

    assert result["status"] == "ok"
    assert result["project_id"] == project_id

    async with session_factory() as session:
        rows = (
            await session.execute(
                KnowledgeGraphHealthCheck.__table__.select().where(
                    KnowledgeGraphHealthCheck.project_id == project_id
                )
            )
        ).all()
    assert len(rows) == 1


async def test_health_check_worker_reports_failure_without_raising(seeded_project, monkeypatch):
    _session_factory, project_id = seeded_project

    async def _boom(self, *_args, **_kwargs):
        raise RuntimeError("simulated health-check failure")

    from app.services.knowledge_graph_health import KnowledgeGraphHealthService

    monkeypatch.setattr(KnowledgeGraphHealthService, "run_health_check", _boom)

    result = await workflows.run_knowledge_graph_health_check(
        {}, tenant_id=1, project_id=project_id
    )

    assert result["status"] == "error"
    assert "simulated health-check failure" in result["error"]
