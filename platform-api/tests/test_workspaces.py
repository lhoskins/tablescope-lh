"""Tests for named, multi-card project workspaces."""

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
    import app.routes.tenants_users as tenants_module

    monkeypatch.setattr(tenants_module, "SupabaseAuthService", _FakeSupabase)
    monkeypatch.setattr(tenants_module, "EmailService", _FakeEmail)


def _headers(tenant_id: int, user_id: int, role: str = "editor") -> dict:
    token = create_access_token(
        sub="u", tenant_id=tenant_id, user_id=user_id, role=role
    )
    return {"Authorization": f"Bearer {token}"}


async def _make_user(client, service_headers, tenant_id, email, role="editor"):
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


async def _setup(client, service_headers, slug: str):
    r = await client.post(
        "/api/tenants",
        json={"slug": slug, "name": f"{slug} tenant"},
        headers=service_headers,
    )
    assert r.status_code == 201
    tenant = r.json()

    owner = await _make_user(client, service_headers, tenant["id"], f"owner-{slug}@t.com")
    other = await _make_user(client, service_headers, tenant["id"], f"other-{slug}@t.com")
    owner_headers = _headers(tenant["id"], owner["id"])
    other_headers = _headers(tenant["id"], other["id"])

    r = await client.post(
        "/api/projects",
        json={"name": "WS Project", "description": "x", "is_shared": True},
        headers=owner_headers,
    )
    assert r.status_code == 201
    project = r.json()

    r = await client.put(
        f"/api/projects/{project['id']}",
        json={"is_shared": True},
        headers=owner_headers,
    )
    assert r.status_code == 200, r.text
    project = r.json()

    r = await client.post(
        f"/api/projects/{project['id']}/members",
        json={"user_id": other["id"], "role": "editor"},
        headers=owner_headers,
    )
    assert r.status_code == 201, r.text

    return tenant, project, owner_headers, other_headers


async def test_create_workspace_is_private_with_ordered_cards(client, service_headers):
    _tenant, project, owner_headers, _other = await _setup(client, service_headers, "ws-create")

    r = await client.post(
        f"/api/projects/{project['id']}/workspaces",
        json={
            "name": "Q3 Review",
            "cards": [
                {"resource_type": "table", "resource_id": "1"},
                {"resource_type": "dashboard", "resource_id": "2"},
            ],
        },
        headers=owner_headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "Q3 Review"
    assert body["visibility"] == "private"
    assert body["published_at"] is None
    assert [c["position"] for c in body["cards"]] == [0, 1]
    assert [c["view_mode"] for c in body["cards"]] == ["card", "card"]


async def test_private_workspace_hidden_from_other_member(client, service_headers):
    _tenant, project, owner_headers, other_headers = await _setup(
        client, service_headers, "ws-private"
    )
    pid = project["id"]

    r = await client.post(
        f"/api/projects/{pid}/workspaces",
        json={"name": "Secret"},
        headers=owner_headers,
    )
    workspace = r.json()

    r = await client.get(f"/api/projects/{pid}/workspaces", headers=other_headers)
    assert r.status_code == 200
    assert workspace["id"] not in {w["id"] for w in r.json()}

    r = await client.get(
        f"/api/projects/{pid}/workspaces/{workspace['id']}", headers=other_headers
    )
    assert r.status_code == 403


async def test_publish_then_unpublish_toggles_member_visibility(client, service_headers):
    _tenant, project, owner_headers, other_headers = await _setup(
        client, service_headers, "ws-publish"
    )
    pid = project["id"]

    workspace = (
        await client.post(
            f"/api/projects/{pid}/workspaces",
            json={"name": "Shared Board"},
            headers=owner_headers,
        )
    ).json()
    wid = workspace["id"]

    r = await client.post(
        f"/api/projects/{pid}/workspaces/{wid}/publish", headers=owner_headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["visibility"] == "shared_project"
    assert r.json()["published_at"] is not None

    r = await client.get(f"/api/projects/{pid}/workspaces", headers=other_headers)
    assert wid in {w["id"] for w in r.json()}
    r = await client.get(f"/api/projects/{pid}/workspaces/{wid}", headers=other_headers)
    assert r.status_code == 200

    r = await client.post(
        f"/api/projects/{pid}/workspaces/{wid}/unpublish", headers=owner_headers
    )
    assert r.status_code == 200
    assert r.json()["visibility"] == "private"
    assert r.json()["published_at"] is None

    r = await client.get(f"/api/projects/{pid}/workspaces/{wid}", headers=other_headers)
    assert r.status_code == 403


async def test_mutations_are_owner_only(client, service_headers):
    _tenant, project, owner_headers, other_headers = await _setup(
        client, service_headers, "ws-owner-only"
    )
    pid = project["id"]

    wid = (
        await client.post(
            f"/api/projects/{pid}/workspaces",
            json={"name": "Mine"},
            headers=owner_headers,
        )
    ).json()["id"]
    # Published, so the non-owner can read it but still may not change it.
    await client.post(f"/api/projects/{pid}/workspaces/{wid}/publish", headers=owner_headers)

    r = await client.patch(
        f"/api/projects/{pid}/workspaces/{wid}",
        json={"name": "Hijacked"},
        headers=other_headers,
    )
    assert r.status_code == 403

    r = await client.post(
        f"/api/projects/{pid}/workspaces/{wid}/unpublish", headers=other_headers
    )
    assert r.status_code == 403

    r = await client.delete(
        f"/api/projects/{pid}/workspaces/{wid}", headers=other_headers
    )
    assert r.status_code == 403


async def test_patch_replaces_cards_and_view_modes(client, service_headers):
    _tenant, project, owner_headers, _other = await _setup(client, service_headers, "ws-patch")
    pid = project["id"]

    wid = (
        await client.post(
            f"/api/projects/{pid}/workspaces",
            json={
                "name": "Board",
                "cards": [
                    {"resource_type": "table", "resource_id": "1"},
                    {"resource_type": "dashboard", "resource_id": "2"},
                ],
            },
            headers=owner_headers,
        )
    ).json()["id"]

    r = await client.patch(
        f"/api/projects/{pid}/workspaces/{wid}",
        json={
            "name": "Renamed Board",
            "cards": [
                {"resource_type": "dashboard", "resource_id": "2", "view_mode": "full"},
                {"resource_type": "document", "resource_id": "9", "view_mode": "row"},
            ],
        },
        headers=owner_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Renamed Board"
    assert [(c["resource_type"], c["view_mode"], c["position"]) for c in body["cards"]] == [
        ("dashboard", "full", 0),
        ("document", "row", 1),
    ]


async def test_patch_rejects_unknown_view_mode(client, service_headers):
    _tenant, project, owner_headers, _other = await _setup(client, service_headers, "ws-viewmode")
    pid = project["id"]

    wid = (
        await client.post(
            f"/api/projects/{pid}/workspaces", json={"name": "B"}, headers=owner_headers
        )
    ).json()["id"]

    r = await client.patch(
        f"/api/projects/{pid}/workspaces/{wid}",
        json={"cards": [{"resource_type": "table", "resource_id": "1", "view_mode": "grid"}]},
        headers=owner_headers,
    )
    assert r.status_code == 400


async def test_delete_removes_workspace(client, service_headers):
    _tenant, project, owner_headers, _other = await _setup(client, service_headers, "ws-delete")
    pid = project["id"]

    wid = (
        await client.post(
            f"/api/projects/{pid}/workspaces",
            json={"name": "Temp", "cards": [{"resource_type": "table", "resource_id": "1"}]},
            headers=owner_headers,
        )
    ).json()["id"]

    r = await client.delete(f"/api/projects/{pid}/workspaces/{wid}", headers=owner_headers)
    assert r.status_code == 200, r.text

    r = await client.get(f"/api/projects/{pid}/workspaces/{wid}", headers=owner_headers)
    assert r.status_code == 404
