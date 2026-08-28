"""TS-ISO-009: conversational-analytics' project access check must reject a
deactivated/removed ProjectMember row, matching every other membership check
in this codebase. Confirmed live: this was the sole check that accepted an
inactive member.

Run from ``platform-api``: ``pytest -q tests/test_conversational_analytics_membership_check.py``.
"""

from __future__ import annotations

import pytest

from app.auth.jwt import create_access_token
from app.models.project import Project, ProjectMember

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


def _headers(tenant_id: int, user_id: int) -> dict:
    token = create_access_token(sub="u", tenant_id=tenant_id, user_id=user_id, role="viewer")
    return {"Authorization": f"Bearer {token}"}


async def test_inactive_member_denied_recent_conversations(
    client, db_session, service_headers
):
    r = await client.post(
        "/api/tenants", json={"slug": "ca-inactive", "name": "ca-inactive tenant"}, headers=service_headers
    )
    tenant_id = r.json()["id"]

    r = await client.post(
        f"/api/tenants/{tenant_id}/users",
        json={
            "email": "owner@ca-inactive.com",
            "display_name": "Owner",
            "role": "editor",
            "external_id": "ext-owner",
        },
        headers=service_headers,
    )
    owner_id = r.json()["id"]

    r = await client.post(
        f"/api/tenants/{tenant_id}/users",
        json={
            "email": "removed@ca-inactive.com",
            "display_name": "Removed",
            "role": "editor",
            "external_id": "ext-removed",
        },
        headers=service_headers,
    )
    removed_id = r.json()["id"]

    project = Project(tenant_id=tenant_id, owner_id=owner_id, name="P", is_shared=True)
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    db_session.add(
        ProjectMember(project_id=project.id, user_id=removed_id, role="viewer", is_active=False)
    )
    await db_session.commit()

    r = await client.get(
        f"/api/conversational-analytics/projects/{project.id}/recent-conversations",
        headers=_headers(tenant_id, removed_id),
    )
    assert r.status_code == 403


async def test_active_member_allowed_recent_conversations(
    client, db_session, service_headers
):
    r = await client.post(
        "/api/tenants", json={"slug": "ca-active", "name": "ca-active tenant"}, headers=service_headers
    )
    tenant_id = r.json()["id"]

    r = await client.post(
        f"/api/tenants/{tenant_id}/users",
        json={
            "email": "owner@ca-active.com",
            "display_name": "Owner",
            "role": "editor",
            "external_id": "ext-owner2",
        },
        headers=service_headers,
    )
    owner_id = r.json()["id"]

    r = await client.post(
        f"/api/tenants/{tenant_id}/users",
        json={
            "email": "member@ca-active.com",
            "display_name": "Member",
            "role": "editor",
            "external_id": "ext-member2",
        },
        headers=service_headers,
    )
    member_id = r.json()["id"]

    project = Project(tenant_id=tenant_id, owner_id=owner_id, name="P", is_shared=True)
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    db_session.add(
        ProjectMember(project_id=project.id, user_id=member_id, role="viewer", is_active=True)
    )
    await db_session.commit()

    r = await client.get(
        f"/api/conversational-analytics/projects/{project.id}/recent-conversations",
        headers=_headers(tenant_id, member_id),
    )
    assert r.status_code == 200
