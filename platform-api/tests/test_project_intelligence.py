"""Tests for the Intelligence endpoints (Concept A Phase 3).

Covers the project-scoped metadata catalog and activity/audit feed that back
the Metadata Catalog and Audit Log screens.
"""

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


async def _setup(client, service_headers, slug: str):
    r = await client.post(
        "/api/tenants",
        json={"slug": slug, "name": f"{slug} tenant"},
        headers=service_headers,
    )
    assert r.status_code == 201
    tenant = r.json()

    r = await client.post(
        f"/api/tenants/{tenant['id']}/users",
        json={
            "email": f"{slug}@test.com",
            "display_name": "Intel User",
            "role": "editor",
            "external_id": f"ext-{slug}",
        },
        headers=service_headers,
    )
    assert r.status_code == 201
    user = r.json()

    headers = _editor_headers(tenant["id"], user["id"])
    r = await client.post(
        "/api/projects",
        json={"name": "Intel Project", "description": "x", "is_shared": False},
        headers=headers,
    )
    assert r.status_code == 201
    return tenant, user, r.json(), headers


async def test_metadata_catalog_shape(client, service_headers) -> None:
    _, _, project, headers = await _setup(client, service_headers, "cat")
    pid = project["id"]

    r = await client.get(
        f"/api/projects/{pid}/metadata-catalog", headers=headers
    )
    assert r.status_code == 200
    body = r.json()
    assert body["tables"] == []
    assert body["documents"] == []


async def test_metadata_catalog_rejects_other_tenant(
    client, service_headers
) -> None:
    _, _, project, _ = await _setup(client, service_headers, "cat-a")
    _, _, _, other_headers = await _setup(client, service_headers, "cat-b")

    r = await client.get(
        f"/api/projects/{project['id']}/metadata-catalog",
        headers=other_headers,
    )
    assert r.status_code == 404


async def test_activity_feed_from_queries_and_dashboards(
    client, service_headers
) -> None:
    _, _, project, headers = await _setup(client, service_headers, "audit")
    pid = project["id"]

    r = await client.post(
        f"/api/projects/{pid}/queries",
        json={
            "name": "Top Suppliers",
            "left_datasource": "inventory_db",
            "ai_generated": True,
        },
        headers=headers,
    )
    assert r.status_code == 201

    r = await client.post(
        f"/api/projects/{pid}/queries",
        json={"name": "Manual Lookup", "left_datasource": "orders_db"},
        headers=headers,
    )
    assert r.status_code == 201

    r = await client.post(
        f"/api/projects/{pid}/dashboards",
        json={"name": "Ops Overview", "description": "d", "config": {}},
        headers=headers,
    )
    assert r.status_code == 201

    r = await client.get(f"/api/projects/{pid}/activity", headers=headers)
    assert r.status_code == 200
    body = r.json()

    events = body["events"]
    titles = {e["title"] for e in events}
    assert "Query saved: Top Suppliers" in titles
    assert "Query saved: Manual Lookup" in titles
    assert "Dashboard created: Ops Overview" in titles

    stats = body["stats"]
    assert stats["total_events"] == len(events)
    assert stats["ai_actions"] >= 1  # the AI-generated query
    assert stats["isolation_violations"] == 0
    assert stats["active_users"] >= 1

    # Newest first ordering by timestamp.
    timestamps = [e["ts"] for e in events]
    assert timestamps == sorted(timestamps, reverse=True)


async def test_activity_feed_rejects_other_tenant(
    client, service_headers
) -> None:
    _, _, project, _ = await _setup(client, service_headers, "audit-a")
    _, _, _, other_headers = await _setup(client, service_headers, "audit-b")

    r = await client.get(
        f"/api/projects/{project['id']}/activity", headers=other_headers
    )
    assert r.status_code == 404
