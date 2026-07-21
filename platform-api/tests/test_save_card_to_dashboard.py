"""Tests for saving a single insight card chart to a dashboard."""

from __future__ import annotations

import pytest

from app.auth.jwt import create_access_token
from app.services.supabase_auth_service import SupabaseAuthService, SupabaseUser

pytestmark = pytest.mark.anyio


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
    async def send_transactional_email(
        self, *, to, template, variables, subject=None, reply_to=None
    ) -> bool:
        return True


@pytest.fixture(autouse=True)
def _mock_supabase(monkeypatch):
    import app.routes.tenants as tenants_module

    monkeypatch.setattr(tenants_module, "SupabaseAuthService", _FakeSupabase)
    monkeypatch.setattr(tenants_module, "EmailService", _FakeEmail)


def _headers(tenant_id: int, user_id: int, role: str = "editor") -> dict:
    token = create_access_token(
        sub="u", tenant_id=tenant_id, user_id=user_id, role=role
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
            "display_name": "Save User",
            "role": "editor",
            "external_id": f"ext-{slug}",
        },
        headers=service_headers,
    )
    assert r.status_code == 201
    user = r.json()
    headers = _headers(tenant["id"], user["id"])

    r = await client.post(
        "/api/projects",
        json={"name": "Save Project", "description": "x", "is_shared": False},
        headers=headers,
    )
    assert r.status_code == 201
    project = r.json()
    return tenant, user, project, headers


async def test_save_card_creates_new_dashboard(client, service_headers) -> None:
    _, _, project, headers = await _setup(client, service_headers, "save-new")

    payload = {
        "project_id": project["id"],
        "dashboard_name": "New insight dashboard",
        "title": "SLA breach",
        "sql": 'SELECT month, amount FROM "sales" ORDER BY month',
        "chartType": "bar",
        "labelColumn": "month",
        "valueColumn": "amount",
    }
    r = await client.post(
        "/api/ai/home/save-card-to-dashboard",
        json=payload,
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "saved"
    assert body["name"] == payload["dashboard_name"]
    assert body["project_id"] == project["id"]
    assert body["query_id"]
    assert body["widget_id"]

    # Dashboard is persisted and retrievable.
    r = await client.get(
        f"/api/projects/{project['id']}/dashboards",
        headers=headers,
    )
    assert r.status_code == 200
    dashboards = r.json()
    assert len(dashboards) == 1
    assert dashboards[0]["name"] == payload["dashboard_name"]


async def test_save_card_appends_to_existing_dashboard(client, service_headers) -> None:
    _, _, project, headers = await _setup(client, service_headers, "save-exist")

    new_payload = {
        "project_id": project["id"],
        "dashboard_name": "Existing dashboard",
        "title": "First widget",
        "sql": 'SELECT a, b FROM "sales"',
        "chartType": "line",
        "labelColumn": "a",
        "valueColumn": "b",
    }
    r = await client.post(
        "/api/ai/home/save-card-to-dashboard",
        json=new_payload,
        headers=headers,
    )
    dashboard_id = r.json()["dashboard_id"]

    append_payload = {
        "project_id": project["id"],
        "dashboard_id": dashboard_id,
        "title": "Second widget",
        "sql": 'SELECT a, c FROM "sales"',
        "chartType": "pie",
        "labelColumn": "a",
        "valueColumn": "c",
    }
    r = await client.post(
        "/api/ai/home/save-card-to-dashboard",
        json=append_payload,
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dashboard_id"] == dashboard_id

    r = await client.get(
        f"/api/projects/{project['id']}/dashboards/{dashboard_id}",
        headers=headers,
    )
    assert r.status_code == 200
    dashboard = r.json()
    assert len(dashboard["config"]["widgets"]) == 2


async def test_save_card_rejects_both_dashboard_id_and_name(
    client, service_headers
) -> None:
    _, _, project, headers = await _setup(client, service_headers, "save-reject")

    payload = {
        "project_id": project["id"],
        "dashboard_id": 1,
        "dashboard_name": "New",
        "title": "Bad request",
        "sql": 'SELECT 1',
    }
    r = await client.post(
        "/api/ai/home/save-card-to-dashboard",
        json=payload,
        headers=headers,
    )
    assert r.status_code == 422


async def test_save_card_allows_source_project_id(client, service_headers) -> None:
    _, _, project, headers = await _setup(client, service_headers, "save-source")

    payload = {
        "project_id": project["id"],
        "source_project_id": project["id"],
        "dashboard_name": "Sourced dashboard",
        "title": "SLA breach",
        "sql": 'SELECT month, amount FROM "sales" ORDER BY month',
        "chartType": "bar",
        "labelColumn": "month",
        "valueColumn": "amount",
    }
    r = await client.post(
        "/api/ai/home/save-card-to-dashboard",
        json=payload,
        headers=headers,
    )
    assert r.status_code == 200, r.text


async def test_save_card_rejects_source_project_mismatch(
    client, service_headers
) -> None:
    _, _, project_a, headers = await _setup(
        client, service_headers, "save-source-a"
    )

    r = await client.post(
        "/api/projects",
        json={"name": "Project B", "description": "x", "is_shared": False},
        headers=headers,
    )
    assert r.status_code == 201
    project_b = r.json()

    # New-dashboard path: the card claims project A as its source but targets B.
    payload = {
        "project_id": project_b["id"],
        "source_project_id": project_a["id"],
        "dashboard_name": "Cross-project dashboard",
        "title": "SLA breach",
        "sql": 'SELECT 1',
    }
    r = await client.post(
        "/api/ai/home/save-card-to-dashboard",
        json=payload,
        headers=headers,
    )
    assert r.status_code == 400, r.text
    assert "source project" in r.text.lower()

    # Existing-dashboard path: create a dashboard in B, then try to save a card
    # sourced from A into it.
    r = await client.post(
        "/api/ai/home/save-card-to-dashboard",
        json={
            "project_id": project_b["id"],
            "dashboard_name": "B dashboard",
            "title": "First widget",
            "sql": 'SELECT 1',
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    dashboard_id = r.json()["dashboard_id"]

    payload = {
        "project_id": project_b["id"],
        "source_project_id": project_a["id"],
        "dashboard_id": dashboard_id,
        "title": "Second widget",
        "sql": 'SELECT 1',
    }
    r = await client.post(
        "/api/ai/home/save-card-to-dashboard",
        json=payload,
        headers=headers,
    )
    assert r.status_code == 400, r.text
    assert "source project" in r.text.lower()
