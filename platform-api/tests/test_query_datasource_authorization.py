"""Route-level tests for the project-authorization fix on /api/query/datasource
(TS-ISO-002).

Live finding: this endpoint accepted a project_id from any authenticated
same-tenant VIEWER with no check that they actually belonged to that
project. Because a shared project's query routes to the OWNER's VDB, that
meant an unrelated same-tenant user could supply another user's shared
project_id and have arbitrary SQL executed against that VDB.

Run from ``platform-api``: ``pytest -q tests/test_query_datasource_authorization.py``.
"""

from __future__ import annotations

import pytest

from app.auth.jwt import create_access_token
from app.models.project import Project, ProjectMember
from app.models.user_vdb import UserVDB

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _mock_supabase(monkeypatch):
    import app.routes.tenants_users as tenants_module
    from app.services.supabase_auth_service import SupabaseAuthService, SupabaseUser

    class _FakeSupabase(SupabaseAuthService):
        def __init__(self) -> None:
            pass

        async def create_or_invite_user(
            self, email, *, first_name=None, last_name=None, redirect_to=None
        ) -> SupabaseUser:
            return SupabaseUser(id=f"supa-{email}", email=email, created=True, action_link="x")

    class _FakeEmail:
        async def send_transactional_email(
            self, *, to, template, variables, subject=None, reply_to=None
        ) -> bool:
            return True

    monkeypatch.setattr(tenants_module, "SupabaseAuthService", _FakeSupabase)
    monkeypatch.setattr(tenants_module, "EmailService", _FakeEmail)


def _headers(tenant_id: int, user_id: int, role: str = "viewer") -> dict:
    token = create_access_token(sub="u", tenant_id=tenant_id, user_id=user_id, role=role)
    return {"Authorization": f"Bearer {token}"}


async def _tenant(client, service_headers, slug: str) -> int:
    r = await client.post(
        "/api/tenants", json={"slug": slug, "name": f"{slug} tenant"}, headers=service_headers
    )
    assert r.status_code == 201
    return r.json()["id"]


async def _user(client, service_headers, tenant_id: int, email: str) -> int:
    r = await client.post(
        f"/api/tenants/{tenant_id}/users",
        json={
            "email": email,
            "display_name": "Q User",
            "role": "editor",
            "external_id": f"ext-{email}",
        },
        headers=service_headers,
    )
    assert r.status_code == 201
    return r.json()["id"]


async def test_unrelated_same_tenant_user_cannot_query_a_shared_project(
    client, db_session, service_headers
):
    tenant_id = await _tenant(client, service_headers, "qd-shared-outsider")
    owner_id = await _user(client, service_headers, tenant_id, "owner@qd-shared.com")
    outsider_id = await _user(client, service_headers, tenant_id, "outsider@qd-shared.com")

    project = Project(tenant_id=tenant_id, owner_id=owner_id, name="Shared", is_shared=True)
    db_session.add(project)
    db_session.add(
        UserVDB(tenant_id=tenant_id, user_id=owner_id, vdb_id="owner-vdb", vdb_username="u", encrypted_password="p", is_active=True)
    )
    await db_session.commit()
    await db_session.refresh(project)

    r = await client.post(
        "/api/query/datasource",
        json={
            "project_id": project.id,
            "sql": 'SELECT * FROM "t"',
        },
        headers=_headers(tenant_id, outsider_id),
    )
    assert r.status_code == 403


async def test_active_member_of_shared_project_passes_authorization(
    client, db_session, service_headers, monkeypatch
):
    """Confirms the fix denies the RIGHT case (above) without also denying
    a legitimate member -- authorization passes and the route proceeds to
    (mocked) Teiid execution."""
    tenant_id = await _tenant(client, service_headers, "qd-shared-member")
    owner_id = await _user(client, service_headers, tenant_id, "owner@qd-member.com")
    member_id = await _user(client, service_headers, tenant_id, "member@qd-member.com")

    project = Project(tenant_id=tenant_id, owner_id=owner_id, name="Shared", is_shared=True)
    db_session.add(project)
    db_session.add(
        UserVDB(tenant_id=tenant_id, user_id=owner_id, vdb_id="owner-vdb", vdb_username="u", encrypted_password="p", is_active=True)
    )
    await db_session.commit()
    await db_session.refresh(project)
    db_session.add(
        ProjectMember(project_id=project.id, user_id=member_id, role="viewer", is_active=True)
    )
    await db_session.commit()

    import app.routes.query as query_module

    async def fake_run_sql(**kwargs):
        return {"columns": ["x"], "rows": [], "rowCount": 0}

    class _FakeEndpoint:
        pg_host = "localhost"
        pg_port = 5433

    class _FakeResolver:
        def __init__(self, session):
            pass

        async def resolve_for_org(self, tenant_id):
            return _FakeEndpoint()

    monkeypatch.setattr(query_module, "_run_sql", fake_run_sql)
    monkeypatch.setattr(query_module, "TenantTeiidResolver", _FakeResolver)

    r = await client.post(
        "/api/query/datasource",
        json={"project_id": project.id, "sql": 'SELECT * FROM "t"'},
        headers=_headers(tenant_id, member_id),
    )
    # Authorization passed (no 403); whatever happens downstream against the
    # mocked Teiid path is not this test's concern.
    assert r.status_code != 403


async def test_inactive_member_cannot_query_a_shared_project(
    client, db_session, service_headers
):
    tenant_id = await _tenant(client, service_headers, "qd-inactive")
    owner_id = await _user(client, service_headers, tenant_id, "owner@qd-inactive.com")
    removed_id = await _user(client, service_headers, tenant_id, "removed@qd-inactive.com")

    project = Project(tenant_id=tenant_id, owner_id=owner_id, name="Shared", is_shared=True)
    db_session.add(project)
    db_session.add(
        UserVDB(tenant_id=tenant_id, user_id=owner_id, vdb_id="owner-vdb", vdb_username="u", encrypted_password="p", is_active=True)
    )
    await db_session.commit()
    await db_session.refresh(project)
    db_session.add(
        ProjectMember(project_id=project.id, user_id=removed_id, role="viewer", is_active=False)
    )
    await db_session.commit()

    r = await client.post(
        "/api/query/datasource",
        json={"project_id": project.id, "sql": 'SELECT * FROM "t"'},
        headers=_headers(tenant_id, removed_id),
    )
    assert r.status_code == 403


async def test_table_name_path_rejects_a_table_outside_the_project(
    client, db_session, service_headers, monkeypatch
):
    tenant_id = await _tenant(client, service_headers, "qd-tablename")
    owner_id = await _user(client, service_headers, tenant_id, "owner@qd-tablename.com")

    project = Project(tenant_id=tenant_id, owner_id=owner_id, name="Mine", is_shared=False)
    db_session.add(project)
    db_session.add(
        UserVDB(tenant_id=tenant_id, user_id=owner_id, vdb_id="owner-vdb", vdb_username="u", encrypted_password="p", is_active=True)
    )
    await db_session.commit()
    await db_session.refresh(project)

    import app.routes.query as query_module

    async def fake_project_table_schema(session, *, tenant_id, project_id):
        return [{"table": "allowed_view", "columns": []}]

    monkeypatch.setattr(query_module, "project_table_schema", fake_project_table_schema)

    r = await client.post(
        "/api/query/datasource",
        json={"project_id": project.id, "tableName": "not_my_table"},
        headers=_headers(tenant_id, owner_id),
    )
    assert r.status_code == 403
