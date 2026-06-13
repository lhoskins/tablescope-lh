"""Dashboard CRUD tests via the HTTP API."""

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


def _editor_headers(tenant_id: int = 1, user_id: int = 1) -> dict:
    token = create_access_token(
        sub="u", tenant_id=tenant_id, user_id=user_id, role="editor"
    )
    return {"Authorization": f"Bearer {token}"}


async def _setup_tenant_and_project(client, service_headers):
    r = await client.post(
        "/api/tenants",
        json={"slug": "dash-tenant", "name": "Dashboard Tenant"},
        headers=service_headers,
    )
    assert r.status_code == 201
    tenant = r.json()

    r = await client.post(
        f"/api/tenants/{tenant['id']}/users",
        json={
            "email": "dash@test.com",
            "display_name": "Dash User",
            "role": "editor",
            "external_id": "ext-dash",
        },
        headers=service_headers,
    )
    assert r.status_code == 201
    user = r.json()

    headers = _editor_headers(tenant_id=tenant["id"], user_id=user["id"])
    r = await client.post(
        "/api/projects",
        json={"name": "Sales Project", "description": "test", "is_shared": False},
        headers=headers,
    )
    assert r.status_code == 201
    project = r.json()
    return tenant, user, project, headers


async def test_dashboard_crud_lifecycle(client, service_headers) -> None:
    tenant, user, project, headers = await _setup_tenant_and_project(
        client, service_headers
    )
    pid = project["id"]

    # List empty
    r = await client.get(f"/api/projects/{pid}/dashboards", headers=headers)
    assert r.status_code == 200
    assert r.json() == []

    # Create
    config = {
        "widgets": [
            {
                "id": "w1",
                "type": "line",
                "title": "Revenue Trend",
                "dataSource": {"kind": "query", "queryId": 1},
                "xKey": "month",
                "yKey": "revenue",
                "colSpan": 6,
                "position": 0,
            }
        ]
    }
    r = await client.post(
        f"/api/projects/{pid}/dashboards",
        json={"name": "Q1 Overview", "description": "test dash", "config": config},
        headers=headers,
    )
    assert r.status_code == 201
    dash = r.json()
    assert dash["name"] == "Q1 Overview"
    assert dash["status"] == "draft"
    assert dash["config"]["widgets"][0]["type"] == "line"
    dash_id = dash["id"]

    # Get
    r = await client.get(
        f"/api/projects/{pid}/dashboards/{dash_id}", headers=headers
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Q1 Overview"

    # Update
    r = await client.put(
        f"/api/projects/{pid}/dashboards/{dash_id}",
        json={"name": "Q1 Revenue Dashboard", "status": "live"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Q1 Revenue Dashboard"
    assert r.json()["status"] == "live"

    # List
    r = await client.get(f"/api/projects/{pid}/dashboards", headers=headers)
    assert r.status_code == 200
    assert len(r.json()) == 1

    # Delete
    r = await client.delete(
        f"/api/projects/{pid}/dashboards/{dash_id}", headers=headers
    )
    assert r.status_code == 204

    # Verify gone
    r = await client.get(f"/api/projects/{pid}/dashboards", headers=headers)
    assert r.status_code == 200
    assert r.json() == []


async def test_dashboard_not_found(client, service_headers) -> None:
    _, _, project, headers = await _setup_tenant_and_project(client, service_headers)
    pid = project["id"]

    r = await client.get(f"/api/projects/{pid}/dashboards/9999", headers=headers)
    assert r.status_code == 404


async def test_widget_query_rejects_foreign_view(client, service_headers) -> None:
    """A widget querying a view that is not one of the project's datasources
    (e.g. an AI-hallucinated table from another tenant) must be rejected."""
    _, _, project, headers = await _setup_tenant_and_project(client, service_headers)
    pid = project["id"]

    r = await client.post(
        f"/api/projects/{pid}/dashboards/widget-query",
        json={
            "view_name": "NW_Products_CSV",
            "x_column": "category",
            "y_column": "revenue",
            "aggregation": "sum",
        },
        headers=headers,
    )
    assert r.status_code == 403
    assert "not a datasource" in r.json()["detail"]
