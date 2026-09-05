"""KG-14: the source fingerprint must catch a content change even when the
row's own ``updated_at`` doesn't move -- a bad clock, an import that
preserves timestamps, or a direct SQL write that bypasses the ORM's
``onupdate``. Every test here mutates content and then explicitly restores
``updated_at`` to its original value before recomputing the fingerprint,
simulating exactly that failure mode; a fingerprint that only looked at
``(id, updated_at)`` would be blind to all of them.

Run from `platform-api`: `pytest -q tests/test_kg14_content_hashing.py`.
"""

from __future__ import annotations

import pytest

from app.auth.context import RequestContext
from app.auth.jwt import TokenClaims
from app.models.dashboard import Dashboard
from app.models.file_source_meta import FileSourceMeta
from app.models.project import Project
from app.models.project_context.goals import ProjectGoal
from app.models.saved_query import SavedQuery
from app.services.knowledge_graph_lifecycle import KnowledgeGraphLifecycleManager

pytestmark = pytest.mark.anyio


def _manager(session, tenant_id: int, user_id: int) -> KnowledgeGraphLifecycleManager:
    return KnowledgeGraphLifecycleManager(
        session,
        RequestContext(
            claims=TokenClaims(sub=str(user_id), tenant_id=tenant_id, user_id=user_id, role="editor")
        ),
    )


async def _seed_project(db_session, *, tenant_id: int) -> int:
    project = Project(tenant_id=tenant_id, owner_id=1, name="Content Hash Project", is_shared=False)
    db_session.add(project)
    await db_session.flush()
    return project.id


async def test_saved_query_sql_change_marks_stale_even_with_a_frozen_timestamp(db_session):
    tenant_id = 1301
    project_id = await _seed_project(db_session, tenant_id=tenant_id)
    mgr = _manager(db_session, tenant_id, 1)

    query = SavedQuery(
        project_id=project_id, owner_id=1, name="Revenue",
        sql_text="SELECT 1",
    )
    db_session.add(query)
    await db_session.flush()

    before = await mgr.compute_source_fingerprint(project_id)
    frozen_updated_at = query.updated_at

    query.sql_text = "SELECT 2"
    query.updated_at = frozen_updated_at
    await db_session.flush()

    after = await mgr.compute_source_fingerprint(project_id)
    assert before != after


async def test_project_goal_content_change_marks_stale_even_with_a_frozen_timestamp(db_session):
    tenant_id = 1302
    project_id = await _seed_project(db_session, tenant_id=tenant_id)
    mgr = _manager(db_session, tenant_id, 1)

    goal = ProjectGoal(tenant_id=tenant_id, project_id=project_id, title="Reduce cycle time")
    db_session.add(goal)
    await db_session.flush()

    before = await mgr.compute_source_fingerprint(project_id)
    frozen_updated_at = goal.updated_at

    goal.description = "New description that changes the goal's meaning."
    goal.updated_at = frozen_updated_at
    await db_session.flush()

    after = await mgr.compute_source_fingerprint(project_id)
    assert before != after


async def test_file_source_content_hash_change_marks_stale_even_with_a_frozen_timestamp(
    db_session,
):
    tenant_id = 1303
    project_id = await _seed_project(db_session, tenant_id=tenant_id)
    mgr = _manager(db_session, tenant_id, 1)

    fs = FileSourceMeta(
        tenant_id=tenant_id, owner_id=1, project_id=project_id,
        view_name="orders", file_name="orders.csv", archived=False,
        content_sha256="a" * 64,
    )
    db_session.add(fs)
    await db_session.flush()

    before = await mgr.compute_source_fingerprint(project_id)
    frozen_updated_at = fs.updated_at

    # Simulates a re-upload of a changed file whose row-level content hash
    # was recomputed but whose updated_at was preserved by the import.
    fs.content_sha256 = "b" * 64
    fs.updated_at = frozen_updated_at
    await db_session.flush()

    after = await mgr.compute_source_fingerprint(project_id)
    assert before != after


async def test_dashboard_config_change_marks_stale_even_with_a_frozen_timestamp(db_session):
    tenant_id = 1304
    project_id = await _seed_project(db_session, tenant_id=tenant_id)
    mgr = _manager(db_session, tenant_id, 1)

    dashboard = Dashboard(
        tenant_id=tenant_id, project_id=project_id, owner_id=1,
        name="Ops Dashboard", config={"widgets": []},
    )
    db_session.add(dashboard)
    await db_session.flush()

    before = await mgr.compute_source_fingerprint(project_id)
    frozen_updated_at = dashboard.updated_at

    dashboard.config = {"widgets": [{"id": "w1", "title": "New Widget"}]}
    dashboard.updated_at = frozen_updated_at
    await db_session.flush()

    after = await mgr.compute_source_fingerprint(project_id)
    assert before != after


async def test_identical_content_produces_an_identical_fingerprint(db_session):
    """Regression check: the content hash must not introduce nondeterminism
    (e.g. dict key ordering) that flags a project stale when nothing changed."""
    tenant_id = 1305
    project_id = await _seed_project(db_session, tenant_id=tenant_id)
    mgr = _manager(db_session, tenant_id, 1)

    db_session.add(
        SavedQuery(project_id=project_id, owner_id=1, name="Revenue", sql_text="SELECT 1")
    )
    await db_session.flush()

    first = await mgr.compute_source_fingerprint(project_id)
    second = await mgr.compute_source_fingerprint(project_id)
    assert first == second
