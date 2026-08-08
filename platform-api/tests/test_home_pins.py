"""Tests for the Home pins CRUD API."""

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
    async def send_transactional_email(
        self, *, to, template, variables, subject=None, reply_to=None
    ) -> bool:
        return True


@pytest.fixture(autouse=True)
def _mock_supabase(monkeypatch):
    import app.routes.tenants_users as tenants_module

    monkeypatch.setattr(tenants_module, "SupabaseAuthService", _FakeSupabase)
    monkeypatch.setattr(tenants_module, "EmailService", _FakeEmail)



pytestmark = pytest.mark.anyio


def _headers(tenant_id: int, user_id: int, role: str = "editor") -> dict:
    token = create_access_token(
        sub="u", tenant_id=tenant_id, user_id=user_id, role=role
    )
    return {"Authorization": f"Bearer {token}"}


async def _setup_tenant_user(client, service_headers, slug: str):
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
            "display_name": "Home User",
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
        json={"name": "Home Project", "description": "x", "is_shared": False},
        headers=headers,
    )
    assert r.status_code == 201
    project = r.json()
    return tenant, user, project, headers


async def test_create_and_list_insight_pin(client, service_headers) -> None:
    _, _, project, headers = await _setup_tenant_user(
        client, service_headers, "home-insight"
    )

    payload = {
        "pin_type": "insight_card",
        "pin_key": f"insight:{project['id']}:risk:sla-breach",
        "title": "SLA breach",
        "project_id": project["id"],
        "frozen_payload": {
            "id": "risk-1",
            "projectId": str(project["id"]),
            "insightType": "risk",
            "severity": "critical",
            "title": "SLA breach",
            "summary": "Supplier missed SLA.",
        },
        "layout": {"x": 0, "y": 0, "w": 6, "h": 4},
    }
    r = await client.post("/api/home-pins", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    pin = r.json()
    assert pin["pin_key"] == payload["pin_key"]
    assert pin["title"] == "SLA breach"
    assert pin["project_id"] == project["id"]

    r = await client.get("/api/home-pins", headers=headers)
    assert r.status_code == 200
    pins = r.json()
    assert len(pins) == 1
    assert pins[0]["id"] == pin["id"]


async def test_create_live_widget_pin_requires_accessible_project(
    client, service_headers
) -> None:
    _, _, project, headers = await _setup_tenant_user(
        client, service_headers, "home-live"
    )

    payload = {
        "pin_type": "live_widget",
        "pin_key": f"widget:{project['id']}:w1",
        "title": "Spend widget",
        "project_id": project["id"],
        "config": {
            "widget": {
                "id": "w1",
                "type": "bar",
                "title": "Spend",
                "xColumn": "month",
                "yColumn": "amount",
            }
        },
        "layout": {"x": 0, "y": 0, "w": 6, "h": 4},
    }
    r = await client.post("/api/home-pins", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    pin = r.json()
    assert pin["pin_type"] == "live_widget"


async def test_create_pin_rejects_inaccessible_project(client, service_headers) -> None:
    _, _, _, headers = await _setup_tenant_user(
        client, service_headers, "home-reject"
    )

    payload = {
        "pin_type": "insight_card",
        "pin_key": "insight:99999:risk:other",
        "title": "Other project",
        "project_id": 99999,
        "frozen_payload": {"title": "x"},
    }
    r = await client.post("/api/home-pins", json=payload, headers=headers)
    assert r.status_code == 404


async def test_delete_pin(client, service_headers) -> None:
    _, _, project, headers = await _setup_tenant_user(
        client, service_headers, "home-delete"
    )

    r = await client.post(
        "/api/home-pins",
        json={
            "pin_type": "insight_card",
            "pin_key": f"insight:{project['id']}:risk:delete-me",
            "title": "Delete me",
            "project_id": project["id"],
        },
        headers=headers,
    )
    pin_id = r.json()["id"]

    r = await client.delete(f"/api/home-pins/{pin_id}", headers=headers)
    assert r.status_code == 204

    r = await client.get("/api/home-pins", headers=headers)
    assert r.json() == []


async def test_update_layout(client, service_headers) -> None:
    _, _, project, headers = await _setup_tenant_user(
        client, service_headers, "home-layout"
    )

    r = await client.post(
        "/api/home-pins",
        json={
            "pin_type": "insight_card",
            "pin_key": f"insight:{project['id']}:risk:layout",
            "title": "Layout",
            "project_id": project["id"],
        },
        headers=headers,
    )
    pin_id = r.json()["id"]

    r = await client.patch(
        "/api/home-pins/layout",
        json={
            "layout": [
                {
                    "id": pin_id,
                    "grid_x": 1,
                    "grid_y": 2,
                    "grid_w": 8,
                    "grid_h": 6,
                    "position": 25,
                }
            ]
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    pins = r.json()
    assert pins[0]["layout"]["x"] == 1
    assert pins[0]["layout"]["h"] == 6


async def test_pins_are_isolated_by_user(client, service_headers) -> None:
    tenant, _user1, project, headers1 = await _setup_tenant_user(
        client, service_headers, "home-iso"
    )

    # Create a second user in the same tenant.
    r = await client.post(
        f"/api/tenants/{tenant['id']}/users",
        json={
            "email": "home-iso-2@test.com",
            "display_name": "Home User 2",
            "role": "editor",
            "external_id": "ext-home-iso-2",
        },
        headers=service_headers,
    )
    user2 = r.json()
    headers2 = _headers(tenant["id"], user2["id"])

    r = await client.post(
        "/api/home-pins",
        json={
            "pin_type": "insight_card",
            "pin_key": f"insight:{project['id']}:risk:iso",
            "title": "Isolated",
            "project_id": project["id"],
        },
        headers=headers1,
    )
    assert r.status_code == 201

    r = await client.get("/api/home-pins", headers=headers2)
    assert r.json() == []
