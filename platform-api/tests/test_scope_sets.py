"""Tests for scope sets + the Scope Relationship Builder map endpoints."""

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


def _headers(tenant_id: int, user_id: int, role: str) -> dict:
    token = create_access_token(
        sub="u", tenant_id=tenant_id, user_id=user_id, role=role
    )
    return {"Authorization": f"Bearer {token}"}


async def _setup(client, service_headers):
    r = await client.post(
        "/api/tenants",
        json={"slug": "scope-tenant", "name": "Scope Tenant"},
        headers=service_headers,
    )
    assert r.status_code == 201, r.text
    tenant = r.json()

    r = await client.post(
        f"/api/tenants/{tenant['id']}/users",
        json={
            "email": "owner@test.com",
            "display_name": "owner",
            "role": "editor",
            "external_id": "ext-owner",
        },
        headers=service_headers,
    )
    assert r.status_code == 201, r.text
    owner = r.json()
    owner_headers = _headers(tenant["id"], owner["id"], "editor")

    r = await client.post(
        "/api/projects", json={"name": "Scope Proj"}, headers=owner_headers
    )
    assert r.status_code == 201, r.text
    project = r.json()

    queries = []
    for name, sql in (
        ("Sales", "SELECT CustomerID, Region, Amount FROM sales"),
        ("Customers", "SELECT CustomerID, Region, Name FROM customers"),
    ):
        r = await client.post(
            f"/api/projects/{project['id']}/queries",
            json={"name": name, "sql_text": sql},
            headers=owner_headers,
        )
        assert r.status_code == 201, r.text
        queries.append(r.json())

    return tenant, owner_headers, project, queries


async def test_create_list_and_toggle_scope_set(client, service_headers) -> None:
    _tenant, owner_headers, project, _queries = await _setup(client, service_headers)
    pid = project["id"]

    r = await client.get(
        f"/api/projects/{pid}/scope_sets", headers=owner_headers
    )
    assert r.status_code == 200
    assert r.json() == []

    r = await client.post(
        f"/api/projects/{pid}/scope_sets",
        json={"name": "Customer -> Orders", "description": "saved scope map"},
        headers=owner_headers,
    )
    assert r.status_code == 201, r.text
    scope_set = r.json()
    assert scope_set["name"] == "Customer -> Orders"
    assert scope_set["type"] == "manual"
    assert scope_set["enabled"] is True
    assert scope_set["scope_count"] == 0

    r = await client.get(
        f"/api/projects/{pid}/scope_sets", headers=owner_headers
    )
    assert len(r.json()) == 1

    # Toggle off.
    r = await client.patch(
        f"/api/scope_sets/{scope_set['id']}",
        json={"enabled": False},
        headers=owner_headers,
    )
    assert r.status_code == 200
    assert r.json()["enabled"] is False


async def test_save_and_load_scope_map(client, service_headers) -> None:
    _tenant, owner_headers, project, queries = await _setup(
        client, service_headers
    )
    pid = project["id"]
    qa, qb = queries[0], queries[1]

    r = await client.post(
        f"/api/projects/{pid}/scope_sets",
        json={"name": "Region Match"},
        headers=owner_headers,
    )
    set_id = r.json()["id"]

    payload = {
        "name": "Region Match",
        "tables": [
            {
                "table_key": f"query:{qa['id']}",
                "table_name": qa["name"],
                "query_id": qa["id"],
                "x_position": 100.0,
                "y_position": 200.0,
            },
            {
                "table_key": f"query:{qb['id']}",
                "table_name": qb["name"],
                "query_id": qb["id"],
                "x_position": 500.0,
                "y_position": 200.0,
            },
        ],
        "relationships": [
            {
                "query_id": qa["id"],
                "source_field": "CustomerID",
                "source_table": qa["name"],
                "target_query_id": qb["id"],
                "target_field": "CustomerID",
                "target_table": qb["name"],
                "match_group_id": "grp1",
                "match_mode": "all",
            },
            {
                "query_id": qa["id"],
                "source_field": "Region",
                "target_query_id": qb["id"],
                "target_field": "Region",
                "match_group_id": "grp1",
                "match_mode": "all",
            },
        ],
    }
    r = await client.put(
        f"/api/scope_sets/{set_id}/map", json=payload, headers=owner_headers
    )
    assert r.status_code == 200, r.text
    saved = r.json()
    assert len(saved["tables"]) == 2
    assert len(saved["relationships"]) == 2
    assert {rel["match_group_id"] for rel in saved["relationships"]} == {"grp1"}

    # Reload restores layout + lines.
    r = await client.get(f"/api/scope_sets/{set_id}/map", headers=owner_headers)
    assert r.status_code == 200
    loaded = r.json()
    assert loaded["scope_set"]["scope_count"] == 2
    positions = {t["table_key"]: t["x_position"] for t in loaded["tables"]}
    assert positions[f"query:{qa['id']}"] == 100.0
    assert positions[f"query:{qb['id']}"] == 500.0


async def test_save_map_persists_ai_origin_relationship(
    client, service_headers
) -> None:
    """An accepted AI suggestion (created_by_ai + confidence) must survive Save.

    Issue 1: the Scope Builder now merges accepted suggestions into the links
    collection and sends them in the PUT /map relationships payload; this locks
    the backend round-trip so an AI-origin mapping is persisted and readable.
    """
    _tenant, owner_headers, project, queries = await _setup(client, service_headers)
    pid = project["id"]
    qa, qb = queries[0], queries[1]

    r = await client.post(
        f"/api/projects/{pid}/scope_sets",
        json={"name": "AI Match"},
        headers=owner_headers,
    )
    set_id = r.json()["id"]

    payload = {
        "name": "AI Match",
        "tables": [
            {
                "table_key": f"query:{qa['id']}",
                "table_name": qa["name"],
                "query_id": qa["id"],
                "x_position": 0.0,
                "y_position": 0.0,
            },
            {
                "table_key": f"query:{qb['id']}",
                "table_name": qb["name"],
                "query_id": qb["id"],
                "x_position": 400.0,
                "y_position": 0.0,
            },
        ],
        "relationships": [
            {
                "query_id": qa["id"],
                "source_field": "CustomerID",
                "source_table": qa["name"],
                "target_query_id": qb["id"],
                "target_field": "CustomerID",
                "target_table": qb["name"],
                "match_group_id": "ai-grp",
                "match_mode": "all",
                "confidence_score": 0.82,
                "created_by_ai": True,
            }
        ],
    }
    r = await client.put(
        f"/api/scope_sets/{set_id}/map", json=payload, headers=owner_headers
    )
    assert r.status_code == 200, r.text
    saved_rel = r.json()["relationships"][0]
    assert saved_rel["created_by_ai"] is True
    assert saved_rel["confidence_score"] == 0.82

    # Round-trips via GET (the AI-origin flag + score are not dropped on reload).
    r = await client.get(f"/api/scope_sets/{set_id}/map", headers=owner_headers)
    assert r.status_code == 200
    rel = r.json()["relationships"][0]
    assert rel["created_by_ai"] is True
    assert rel["confidence_score"] == 0.82
    assert rel["source_table"] == qa["name"]
    assert rel["target_table"] == qb["name"]


async def test_scope_builder_tables_and_ai_suggest(
    client, service_headers
) -> None:
    _tenant, owner_headers, project, queries = await _setup(
        client, service_headers
    )
    pid = project["id"]

    r = await client.get(
        f"/api/projects/{pid}/scope-builder/tables", headers=owner_headers
    )
    assert r.status_code == 200
    tables = r.json()
    assert len(tables) == 2
    sales = next(t for t in tables if t["table_name"] == "Sales")
    assert "CustomerID" in sales["fields"]

    r = await client.post(
        f"/api/projects/{pid}/scope_sets",
        json={"name": "AI test"},
        headers=owner_headers,
    )
    set_id = r.json()["id"]

    r = await client.post(
        f"/api/scope_sets/{set_id}/ai-suggest",
        json={"query_ids": [queries[0]["id"], queries[1]["id"]]},
        headers=owner_headers,
    )
    assert r.status_code == 200, r.text
    suggestions = r.json()["suggestions"]
    fields = {s["source_field"] for s in suggestions}
    # CustomerID + Region are shared between the two queries.
    assert "CustomerID" in fields
    assert "Region" in fields


async def test_delete_scope_set(client, service_headers) -> None:
    _tenant, owner_headers, project, _queries = await _setup(
        client, service_headers
    )
    pid = project["id"]
    r = await client.post(
        f"/api/projects/{pid}/scope_sets",
        json={"name": "Temp"},
        headers=owner_headers,
    )
    set_id = r.json()["id"]

    r = await client.delete(
        f"/api/scope_sets/{set_id}", headers=owner_headers
    )
    assert r.status_code == 204

    r = await client.get(f"/api/scope_sets/{set_id}", headers=owner_headers)
    assert r.status_code == 404


async def test_scope_set_exposes_creator_metadata(client, service_headers) -> None:
    _tenant, owner_headers, project, _queries = await _setup(
        client, service_headers
    )
    pid = project["id"]
    r = await client.post(
        f"/api/projects/{pid}/scope_sets",
        json={"name": "Meta"},
        headers=owner_headers,
    )
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["creator_email"] == "owner@test.com"
    assert created["created_at"] is not None
    # Project owner can delete.
    assert created["can_delete"] is True

    r = await client.get(
        f"/api/projects/{pid}/scope_sets", headers=owner_headers
    )
    row = r.json()[0]
    assert row["creator_email"] == "owner@test.com"
    assert row["created_at"] is not None
    assert row["can_delete"] is True


async def test_non_creator_non_admin_cannot_delete(client, service_headers) -> None:
    tenant, owner_headers, project, _queries = await _setup(
        client, service_headers
    )
    pid = project["id"]
    # Owner creates the scope set.
    r = await client.post(
        f"/api/projects/{pid}/scope_sets",
        json={"name": "OwnerScope"},
        headers=owner_headers,
    )
    set_id = r.json()["id"]

    # A different editor (not creator, not project admin) is forbidden.
    r = await client.post(
        f"/api/tenants/{tenant['id']}/users",
        json={
            "email": "other@test.com",
            "display_name": "other",
            "role": "editor",
            "external_id": "ext-other",
        },
        headers=service_headers,
    )
    assert r.status_code == 201, r.text
    other = r.json()
    other_headers = _headers(tenant["id"], other["id"], "editor")

    r = await client.get(
        f"/api/projects/{pid}/scope_sets", headers=other_headers
    )
    assert r.status_code == 200
    assert r.json()[0]["can_delete"] is False

    r = await client.delete(
        f"/api/scope_sets/{set_id}", headers=other_headers
    )
    assert r.status_code == 403

    # Tenant admin can delete.
    admin_headers = _headers(tenant["id"], other["id"], "admin")
    r = await client.delete(
        f"/api/scope_sets/{set_id}", headers=admin_headers
    )
    assert r.status_code == 204


async def test_viewer_cannot_create_scope_set(client, service_headers) -> None:
    _tenant, owner_headers, project, _queries = await _setup(
        client, service_headers
    )
    pid = project["id"]
    viewer_headers = _headers(_tenant_id_of(project), 999, "viewer")
    r = await client.post(
        f"/api/projects/{pid}/scope_sets",
        json={"name": "Nope"},
        headers=viewer_headers,
    )
    assert r.status_code == 403


def _tenant_id_of(project: dict) -> int:
    return project["tenant_id"]


async def test_auto_generate_creates_ai_scope_set_and_is_idempotent(
    client, service_headers
) -> None:
    """POST auto-generate builds the AI set from shared query columns; re-run
    creates no duplicates."""
    _tenant, owner_headers, project, _queries = await _setup(
        client, service_headers
    )
    pid = project["id"]

    r = await client.post(
        f"/api/projects/{pid}/scope_sets/auto-generate", headers=owner_headers
    )
    assert r.status_code == 200, r.text
    ai_set = r.json()
    assert ai_set["type"] == "ai_generated"
    assert ai_set["name"] == "AI Generated Scopes"
    # Sales/Customers share CustomerID + Region → mappings both directions.
    first_count = ai_set["scope_count"]
    assert first_count > 0

    # Idempotent: re-running must not duplicate.
    r = await client.post(
        f"/api/projects/{pid}/scope_sets/auto-generate", headers=owner_headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["scope_count"] == first_count
    assert r.json()["id"] == ai_set["id"]

    # It shows up in the list as a single AI set.
    r = await client.get(
        f"/api/projects/{pid}/scope_sets", headers=owner_headers
    )
    ai_sets = [s for s in r.json() if s["type"] == "ai_generated"]
    assert len(ai_sets) == 1


async def test_auto_generate_requires_editor(client, service_headers) -> None:
    _tenant, owner_headers, project, _queries = await _setup(
        client, service_headers
    )
    pid = project["id"]
    viewer_headers = _headers(_tenant_id_of(project), 999, "viewer")
    r = await client.post(
        f"/api/projects/{pid}/scope_sets/auto-generate", headers=viewer_headers
    )
    assert r.status_code == 403


async def test_on_save_trigger_extends_enabled_ai_set(
    client, service_headers
) -> None:
    """Once the AI set exists+enabled, saving a new sharing query auto-adds
    mappings; with no AI set, saving is a no-op (opt-in)."""
    _tenant, owner_headers, project, _queries = await _setup(
        client, service_headers
    )
    pid = project["id"]

    # No AI set yet → saving a new query must not create one.
    r = await client.post(
        f"/api/projects/{pid}/queries",
        json={"name": "Orders", "sql_text": "SELECT CustomerID, Total FROM orders"},
        headers=owner_headers,
    )
    assert r.status_code == 201
    r = await client.get(
        f"/api/projects/{pid}/scope_sets", headers=owner_headers
    )
    assert [s for s in r.json() if s["type"] == "ai_generated"] == []

    # Enable autoscoping by generating the AI set.
    r = await client.post(
        f"/api/projects/{pid}/scope_sets/auto-generate", headers=owner_headers
    )
    assert r.status_code == 200
    before = r.json()["scope_count"]

    # Saving another sharing query now extends the enabled AI set.
    r = await client.post(
        f"/api/projects/{pid}/queries",
        json={
            "name": "Invoices",
            "sql_text": "SELECT CustomerID, Region FROM invoices",
        },
        headers=owner_headers,
    )
    assert r.status_code == 201
    r = await client.get(
        f"/api/projects/{pid}/scope_sets", headers=owner_headers
    )
    ai_set = next(s for s in r.json() if s["type"] == "ai_generated")
    assert ai_set["scope_count"] > before
