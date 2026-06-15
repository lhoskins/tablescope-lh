"""Saved-query workspace metadata tests (Concept A Queries screen)."""

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


def _editor_headers(tenant_id: int, user_id: int) -> dict:
    token = create_access_token(
        sub="u", tenant_id=tenant_id, user_id=user_id, role="editor"
    )
    return {"Authorization": f"Bearer {token}"}


async def _setup(client, service_headers):
    r = await client.post(
        "/api/tenants",
        json={"slug": "q-tenant", "name": "Query Tenant"},
        headers=service_headers,
    )
    assert r.status_code == 201
    tenant = r.json()

    r = await client.post(
        f"/api/tenants/{tenant['id']}/users",
        json={
            "email": "q@test.com",
            "display_name": "Q User",
            "role": "editor",
            "external_id": "ext-q",
        },
        headers=service_headers,
    )
    assert r.status_code == 201
    user = r.json()

    headers = _editor_headers(tenant["id"], user["id"])
    r = await client.post(
        "/api/projects",
        json={"name": "Supply Chain", "description": "test", "is_shared": False},
        headers=headers,
    )
    assert r.status_code == 201
    return r.json(), headers


async def test_query_metadata_defaults_and_roundtrip(client, service_headers) -> None:
    project, headers = await _setup(client, service_headers)
    pid = project["id"]

    # Defaults
    r = await client.post(
        f"/api/projects/{pid}/queries",
        json={"name": "Manual Query", "left_datasource": "inventory_db"},
        headers=headers,
    )
    assert r.status_code == 201
    manual = r.json()
    assert manual["ai_generated"] is False
    assert manual["is_shared"] is False
    assert manual["run_count"] == 0
    assert manual["avg_runtime_ms"] is None

    # AI-generated + shared round-trips on create
    r = await client.post(
        f"/api/projects/{pid}/queries",
        json={
            "name": "Backorder Rate by Supplier",
            "left_datasource": "inventory_db",
            "ai_generated": True,
            "is_shared": True,
        },
        headers=headers,
    )
    assert r.status_code == 201
    ai = r.json()
    assert ai["ai_generated"] is True
    assert ai["is_shared"] is True

    # Update can change flags
    r = await client.put(
        f"/api/projects/{pid}/queries/{manual['id']}",
        json={"is_shared": True},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["is_shared"] is True

    # List reflects both
    r = await client.get(f"/api/projects/{pid}/queries", headers=headers)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2
    assert {q["name"] for q in rows} == {
        "Manual Query",
        "Backorder Rate by Supplier",
    }
