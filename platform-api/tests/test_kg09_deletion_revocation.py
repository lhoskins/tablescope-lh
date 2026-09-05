"""KG-09: deletion/revocation must actually propagate.

Two concrete, verified gaps fixed here:

1. ``collect_structural_graph`` never filtered ``SavedQuery.is_archived`` --
   archiving a query is this app's soft-delete precondition (a hard DELETE
   requires archiving first, see ``app/routes/projects_queries.py``), but an
   archived query kept appearing in the graph exactly like an active one,
   unlike the analogous ``FileSourceMeta``/``DatabaseDataSource`` "archived"
   filters that already existed.
2. ``ProjectMember`` was never part of ``compute_source_fingerprint``'s
   hashed inputs at all, so revoking or removing a member's project access
   never marked the graph stale -- not immediately, not even eventually via
   the 15-minute staleness cron every other source type relies on.

Run from `platform-api`: `pytest -q tests/test_kg09_deletion_revocation.py`.
"""

from __future__ import annotations

import pytest

from app.auth.context import RequestContext
from app.auth.jwt import TokenClaims
from app.models.project import Project, ProjectMember
from app.models.saved_query import SavedQuery
from app.services.knowledge_graph_context.collectors import collect_structural_graph
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
    project = Project(tenant_id=tenant_id, owner_id=1, name="Deletion Project", is_shared=False)
    db_session.add(project)
    await db_session.flush()
    return project.id


async def test_archived_saved_query_no_longer_appears_in_the_graph(db_session):
    tenant_id = 1901
    project_id = await _seed_project(db_session, tenant_id=tenant_id)

    query = SavedQuery(
        project_id=project_id, owner_id=1, name="Old Report", sql_text="SELECT 1",
        is_archived=True,
    )
    db_session.add(query)
    await db_session.flush()

    nodes, _edges, _hub_key = await collect_structural_graph(
        db_session, tenant_id=tenant_id, project_id=project_id,
    )
    assert [n for n in nodes if n["source_type"] == "saved_query"] == []


async def test_active_saved_query_still_appears_in_the_graph(db_session):
    tenant_id = 1902
    project_id = await _seed_project(db_session, tenant_id=tenant_id)

    query = SavedQuery(
        project_id=project_id, owner_id=1, name="Current Report", sql_text="SELECT 1",
        is_archived=False,
    )
    db_session.add(query)
    await db_session.flush()

    nodes, _edges, _hub_key = await collect_structural_graph(
        db_session, tenant_id=tenant_id, project_id=project_id,
    )
    query_nodes = [n for n in nodes if n["source_type"] == "saved_query"]
    assert len(query_nodes) == 1
    assert query_nodes[0]["source_id"] == query.id


async def test_deactivating_a_member_changes_the_source_fingerprint(db_session):
    tenant_id = 1903
    project_id = await _seed_project(db_session, tenant_id=tenant_id)
    mgr = _manager(db_session, tenant_id, 1)

    member = ProjectMember(project_id=project_id, user_id=42, role="member", is_active=True)
    db_session.add(member)
    await db_session.flush()

    before = await mgr.compute_source_fingerprint(project_id)

    member.is_active = False
    await db_session.flush()

    after = await mgr.compute_source_fingerprint(project_id)
    assert before != after


async def test_removing_a_member_changes_the_source_fingerprint(db_session):
    tenant_id = 1904
    project_id = await _seed_project(db_session, tenant_id=tenant_id)
    mgr = _manager(db_session, tenant_id, 1)

    member = ProjectMember(project_id=project_id, user_id=43, role="member", is_active=False)
    db_session.add(member)
    await db_session.flush()

    before = await mgr.compute_source_fingerprint(project_id)

    await db_session.delete(member)
    await db_session.flush()

    after = await mgr.compute_source_fingerprint(project_id)
    assert before != after
