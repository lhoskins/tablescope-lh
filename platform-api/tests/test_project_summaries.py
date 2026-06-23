"""Tests for /auth/me, /projects/summaries, and /ai/route-prompt."""

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
    async def send_transactional_email(self, *, to, template, variables, subject=None, reply_to=None) -> bool:
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
        json={"slug": "sum-tenant", "name": "Summary Tenant"},
        headers=service_headers,
    )
    assert r.status_code == 201
    tenant = r.json()

    r = await client.post(
        f"/api/tenants/{tenant['id']}/users",
        json={
            "email": "sum@test.com",
            "display_name": "Sum User",
            "role": "editor",
            "external_id": "ext-sum",
        },
        headers=service_headers,
    )
    assert r.status_code == 201
    user = r.json()
    headers = _editor_headers(tenant["id"], user["id"])
    return tenant, user, headers


async def test_auth_me_returns_identity(client, service_headers) -> None:
    tenant, user, headers = await _setup(client, service_headers)
    r = await client.get("/api/auth/me", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "sum@test.com"
    assert body["display_name"] == "Sum User"
    assert body["tenant_name"] == "Summary Tenant"
    assert body["tenant_slug"] == "sum-tenant"
    assert body["role"] == "editor"


async def test_auth_me_requires_auth(client) -> None:
    r = await client.get("/api/auth/me")
    assert r.status_code == 401


async def test_project_summaries_counts_and_status(
    client, service_headers
) -> None:
    tenant, user, headers = await _setup(client, service_headers)

    # No projects yet → empty list.
    r = await client.get("/api/projects/summaries", headers=headers)
    assert r.status_code == 200
    assert r.json() == []

    r = await client.post(
        "/api/projects",
        json={"name": "Supply Chain"},
        headers=headers,
    )
    assert r.status_code == 201
    pid = r.json()["id"]

    # Mark it shared (create always starts private).
    r = await client.put(
        f"/api/projects/{pid}",
        json={"is_shared": True},
        headers=headers,
    )
    assert r.status_code == 200

    # Add a saved query and a dashboard so counts are non-zero.
    r = await client.post(
        f"/api/projects/{pid}/queries",
        json={"name": "Backorder Rate", "sql_text": "SELECT 1"},
        headers=headers,
    )
    assert r.status_code == 201
    r = await client.post(
        f"/api/projects/{pid}/dashboards",
        json={"name": "Overview", "config": {"widgets": []}},
        headers=headers,
    )
    assert r.status_code == 201

    r = await client.get(
        "/api/projects/summaries?recent=true&limit=5", headers=headers
    )
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == pid
    assert row["name"] == "Supply Chain"
    assert row["is_shared"] is True
    assert row["query_count"] == 1
    assert row["dashboard_count"] == 1
    assert row["document_count"] == 0
    # No documents but has activity (query/dashboard) → "active".
    assert row["ai_status"] == "active"
    assert row["member_count"] >= 1


async def test_route_prompt_targets_existing_project(
    client, service_headers
) -> None:
    tenant, user, headers = await _setup(client, service_headers)
    r = await client.post(
        "/api/projects",
        json={"name": "Logistics", "is_shared": False},
        headers=headers,
    )
    assert r.status_code == 201
    pid = r.json()["id"]

    r = await client.post(
        "/api/ai/route-prompt",
        json={"prompt": "supplier delays"},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["route"] == f"/projects/{pid}/ai"
    assert body["prefilled"] == "supplier delays"


async def test_route_prompt_no_project_seeds_new(
    client, service_headers
) -> None:
    tenant, user, headers = await _setup(client, service_headers)
    r = await client.post(
        "/api/ai/route-prompt",
        json={"prompt": "build me something"},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["route"] == "/projects/new"
    assert body["prefilled"] == "build me something"
