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
    async def send_transactional_email(self, *, to, template, variables, subject=None, reply_to=None) -> bool:
        return True


@pytest.fixture(autouse=True)
def _mock_supabase(monkeypatch):
    import app.routes.tenants_users as tenants_module

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


async def test_archive_lifecycle(client, service_headers) -> None:
    project, headers = await _setup(client, service_headers)
    pid = project["id"]

    q = (
        await client.post(
            f"/api/projects/{pid}/queries",
            json={"name": "Archive Me", "left_datasource": "inventory_db"},
            headers=headers,
        )
    ).json()
    qid = q["id"]

    # Archive returns 200 (not 500) and flips the flag with a timestamp.
    r = await client.post(
        f"/api/projects/{pid}/queries/{qid}/archive", json={}, headers=headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_archived"] is True
    assert body["archived_at"] is not None

    # Archived query is hidden from the normal list…
    rows = (
        await client.get(f"/api/projects/{pid}/queries", headers=headers)
    ).json()
    assert all(row["id"] != qid for row in rows)

    # …but visible when archived are explicitly requested, and it persists.
    rows = (
        await client.get(
            f"/api/projects/{pid}/queries?include_archived=true", headers=headers
        )
    ).json()
    assert any(row["id"] == qid and row["is_archived"] for row in rows)

    # Restore brings it back to the active list and clears archive metadata.
    r = await client.post(
        f"/api/projects/{pid}/queries/{qid}/restore", json={}, headers=headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_archived"] is False
    assert r.json()["archived_at"] is None
    rows = (
        await client.get(f"/api/projects/{pid}/queries", headers=headers)
    ).json()
    assert any(row["id"] == qid for row in rows)


async def test_delete_requires_archive_then_succeeds(
    client, service_headers
) -> None:
    project, headers = await _setup(client, service_headers)
    pid = project["id"]

    qid = (
        await client.post(
            f"/api/projects/{pid}/queries",
            json={"name": "Delete Me", "left_datasource": "inventory_db"},
            headers=headers,
        )
    ).json()["id"]

    # A non-archived query cannot be permanently deleted.
    r = await client.delete(
        f"/api/projects/{pid}/queries/{qid}", headers=headers
    )
    assert r.status_code == 409
    assert "archived" in r.json()["detail"].lower()

    # Archive, then delete succeeds and the query is gone.
    await client.post(
        f"/api/projects/{pid}/queries/{qid}/archive", json={}, headers=headers
    )
    r = await client.delete(
        f"/api/projects/{pid}/queries/{qid}", headers=headers
    )
    assert r.status_code == 204, r.text
    rows = (
        await client.get(
            f"/api/projects/{pid}/queries?include_archived=true",
            headers=headers,
        )
    ).json()
    assert all(row["id"] != qid for row in rows)


async def test_delete_blocked_by_scope_dependency_lists_it(
    client, db_session, service_headers
) -> None:
    project, headers = await _setup(client, service_headers)
    pid = project["id"]

    source_id = (
        await client.post(
            f"/api/projects/{pid}/queries",
            json={"name": "Source Q", "left_datasource": "inventory_db"},
            headers=headers,
        )
    ).json()["id"]
    target_id = (
        await client.post(
            f"/api/projects/{pid}/queries",
            json={"name": "Target Q", "left_datasource": "orders_db"},
            headers=headers,
        )
    ).json()["id"]

    # A scope relationship makes Source Q feed Target Q.
    from app.models.query_scope import QueryScope

    db_session.add(
        QueryScope(
            tenant_id=project["tenant_id"],
            project_id=pid,
            query_id=source_id,
            source_field="supplier_id",
            source_table="Source Q",
            target_query_id=target_id,
            target_field="supplier_id",
            target_table="Target Q",
            direction="outgoing",
        )
    )
    await db_session.commit()

    await client.post(
        f"/api/projects/{pid}/queries/{source_id}/archive",
        json={},
        headers=headers,
    )
    r = await client.delete(
        f"/api/projects/{pid}/queries/{source_id}", headers=headers
    )
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "Scope" in detail
    assert "Target Q" in detail


async def test_query_list_enriches_owner_origin_scope(
    client, service_headers
) -> None:
    project, headers = await _setup(client, service_headers)
    pid = project["id"]

    await client.post(
        f"/api/projects/{pid}/queries",
        json={"name": "Manual Query", "left_datasource": "inventory_db"},
        headers=headers,
    )
    await client.post(
        f"/api/projects/{pid}/queries",
        json={
            "name": "AI Query",
            "left_datasource": "inventory_db",
            "ai_generated": True,
        },
        headers=headers,
    )

    rows = (
        await client.get(f"/api/projects/{pid}/queries", headers=headers)
    ).json()
    by_name = {q["name"]: q for q in rows}

    manual = by_name["Manual Query"]
    assert manual["origin"] == "manual"
    assert manual["origin_label"] == "Manual"
    assert manual["owner_name"] == "Q User"
    # No scopes defined yet → no active scope, so the UI shows no icon.
    assert manual["has_active_scope"] is False
    assert manual["active_scope_count"] == 0

    ai = by_name["AI Query"]
    assert ai["origin"] == "ai_generated"
    assert ai["origin_label"] == "AI Generated"
