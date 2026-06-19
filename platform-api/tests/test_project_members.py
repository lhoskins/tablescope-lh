"""Tests for project membership management (addable users + member CRUD)."""

from __future__ import annotations

import pytest

from app.auth.jwt import create_access_token
from app.services.supabase_auth_service import SupabaseAuthService, SupabaseUser


class _FakeSupabase(SupabaseAuthService):
    def __init__(self) -> None:
        pass

    async def create_or_invite_user(
        self, email, *, first_name=None, last_name=None, redirect_to=None
    ) -> SupabaseUser:
        return SupabaseUser(
            id=f"supa-{email}",
            email=email,
            created=True,
            action_link=f"https://invite/{email}",
        )


class _FakeEmail:
    async def send(self, spec, *, to, template) -> bool:
        return True


@pytest.fixture(autouse=True)
def _mock_supabase(monkeypatch):
    import app.routes.tenants as tenants_module

    monkeypatch.setattr(tenants_module, "SupabaseAuthService", _FakeSupabase)
    monkeypatch.setattr(tenants_module, "EmailService", _FakeEmail)


def _headers(tenant_id: int, user_id: int, role: str) -> dict:
    token = create_access_token(
        sub="u", tenant_id=tenant_id, user_id=user_id, role=role
    )
    return {"Authorization": f"Bearer {token}"}


async def _make_user(client, service_headers, tenant_id, email, role):
    r = await client.post(
        f"/api/tenants/{tenant_id}/users",
        json={
            "email": email,
            "display_name": email.split("@")[0],
            "role": role,
            "external_id": f"ext-{email}",
        },
        headers=service_headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _setup(client, service_headers):
    r = await client.post(
        "/api/tenants",
        json={"slug": "mem-tenant", "name": "Member Tenant"},
        headers=service_headers,
    )
    assert r.status_code == 201
    tenant = r.json()

    owner = await _make_user(
        client, service_headers, tenant["id"], "owner@test.com", "editor"
    )
    member = await _make_user(
        client, service_headers, tenant["id"], "member@test.com", "viewer"
    )
    owner_headers = _headers(tenant["id"], owner["id"], "editor")

    r = await client.post(
        "/api/projects", json={"name": "Members Proj"}, headers=owner_headers
    )
    assert r.status_code == 201
    project = r.json()
    return tenant, owner, member, owner_headers, project


async def test_addable_users_excludes_owner_and_active_members(
    client, service_headers
) -> None:
    tenant, owner, member, owner_headers, project = await _setup(
        client, service_headers
    )
    pid = project["id"]

    r = await client.get(
        f"/api/projects/{pid}/addable-users", headers=owner_headers
    )
    assert r.status_code == 200
    ids = {u["user_id"] for u in r.json()}
    assert member["id"] in ids
    assert owner["id"] not in ids

    # Add the member.
    r = await client.post(
        f"/api/projects/{pid}/members",
        json={"user_id": member["id"], "role": "editor"},
        headers=owner_headers,
    )
    assert r.status_code == 201
    assert r.json()["role"] == "editor"

    # Now they are no longer addable.
    r = await client.get(
        f"/api/projects/{pid}/addable-users", headers=owner_headers
    )
    assert member["id"] not in {u["user_id"] for u in r.json()}


async def test_member_role_lifecycle(client, service_headers) -> None:
    tenant, owner, member, owner_headers, project = await _setup(
        client, service_headers
    )
    pid = project["id"]

    await client.post(
        f"/api/projects/{pid}/members",
        json={"user_id": member["id"], "role": "viewer"},
        headers=owner_headers,
    )

    r = await client.put(
        f"/api/projects/{pid}/members/{member['id']}/role",
        json={"role": "admin"},
        headers=owner_headers,
    )
    assert r.status_code == 200
    assert r.json()["role"] == "admin"

    # "Remove" deactivates the member (they drop out of the active member list).
    r = await client.put(
        f"/api/projects/{pid}/members/{member['id']}/deactivate",
        json={},
        headers=owner_headers,
    )
    assert r.status_code == 200
    assert r.json()["is_active"] is False

    r = await client.get(f"/api/projects/{pid}/members", headers=owner_headers)
    active = [m for m in r.json() if m["is_active"]]
    assert member["id"] not in {m["user_id"] for m in active}

    # An inactive member can then be permanently deleted.
    r = await client.delete(
        f"/api/projects/{pid}/members/{member['id']}", headers=owner_headers
    )
    assert r.status_code in (200, 204)


async def test_add_member_rejects_invalid_role(client, service_headers) -> None:
    tenant, owner, member, owner_headers, project = await _setup(
        client, service_headers
    )
    r = await client.post(
        f"/api/projects/{project['id']}/members",
        json={"user_id": member["id"], "role": "superuser"},
        headers=owner_headers,
    )
    assert r.status_code == 400


async def test_addable_users_forbidden_for_non_manager(
    client, service_headers
) -> None:
    tenant, owner, member, owner_headers, project = await _setup(
        client, service_headers
    )
    member_headers = _headers(tenant["id"], member["id"], "viewer")
    r = await client.get(
        f"/api/projects/{project['id']}/addable-users",
        headers=member_headers,
    )
    assert r.status_code == 403
