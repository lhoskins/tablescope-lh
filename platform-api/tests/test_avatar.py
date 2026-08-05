"""Tests for user avatar upload + serving (Issue 7)."""

from __future__ import annotations

import pytest

from app.auth.jwt import create_access_token
from app.config import get_settings
from app.services.supabase_auth_service import SupabaseAuthService, SupabaseUser

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
PNG_BYTES = PNG_MAGIC + b"0" * 64


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
    async def send_transactional_email(self, *, to, template, variables, **kw) -> bool:
        return True


@pytest.fixture(autouse=True)
def _mock_externals(monkeypatch, tmp_path):
    import app.routes.tenants_users as tenants_module

    monkeypatch.setattr(tenants_module, "SupabaseAuthService", _FakeSupabase)
    monkeypatch.setattr(tenants_module, "EmailService", _FakeEmail)
    settings = get_settings()
    monkeypatch.setattr(settings, "s3_enabled", False)
    monkeypatch.setattr(settings, "customer_base_path", str(tmp_path))


async def _make_user(client, service_headers, *, email, ext_id):
    r = await client.post(
        "/api/tenants",
        json={"slug": f"av-{ext_id}", "name": "Avatar Tenant"},
        headers=service_headers,
    )
    assert r.status_code == 201
    tenant = r.json()
    r = await client.post(
        f"/api/tenants/{tenant['id']}/users",
        json={
            "email": email,
            "display_name": "Av User",
            "role": "member",
            "external_id": ext_id,
        },
        headers=service_headers,
    )
    assert r.status_code == 201
    user = r.json()
    token = create_access_token(
        sub=ext_id, tenant_id=tenant["id"], user_id=user["id"], role="member"
    )
    return tenant, user, {"Authorization": f"Bearer {token}"}


async def test_authenticated_user_can_upload_avatar(client, service_headers) -> None:
    _tenant, user, headers = await _make_user(
        client, service_headers, email="a@test.com", ext_id="u1"
    )

    r = await client.post(
        "/api/users/me/avatar",
        files={"file": ("me.png", PNG_BYTES, "image/png")},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["avatar_url"].startswith(f"/api/users/{user['id']}/avatar")
    # No raw filesystem path is exposed.
    assert "/tmp" not in body["avatar_url"]
    assert "customers" not in body["avatar_url"]

    # /auth/me now carries the avatar URL.
    me = await client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["avatar_url"] == body["avatar_url"]

    # The image is served by the opaque URL (no auth needed for <img>).
    img = await client.get(f"/api/users/{user['id']}/avatar")
    assert img.status_code == 200
    assert img.headers["content-type"] == "image/png"
    assert img.content == PNG_BYTES


async def test_unauthenticated_upload_rejected(client, service_headers) -> None:
    await _make_user(client, service_headers, email="b@test.com", ext_id="u2")
    r = await client.post(
        "/api/users/me/avatar",
        files={"file": ("me.png", PNG_BYTES, "image/png")},
    )
    assert r.status_code == 401


async def test_invalid_file_type_rejected(client, service_headers) -> None:
    _tenant, _user, headers = await _make_user(
        client, service_headers, email="c@test.com", ext_id="u3"
    )
    # SVG is explicitly disallowed.
    r = await client.post(
        "/api/users/me/avatar",
        files={"file": ("x.svg", b"<svg></svg>", "image/svg+xml")},
        headers=headers,
    )
    assert r.status_code == 422

    # A PNG content-type with non-image bytes fails the magic-byte check.
    r = await client.post(
        "/api/users/me/avatar",
        files={"file": ("fake.png", b"not an image", "image/png")},
        headers=headers,
    )
    assert r.status_code == 422


async def test_oversized_file_rejected(client, service_headers) -> None:
    _tenant, _user, headers = await _make_user(
        client, service_headers, email="d@test.com", ext_id="u4"
    )
    big = PNG_MAGIC + b"0" * (5 * 1024 * 1024 + 1)
    r = await client.post(
        "/api/users/me/avatar",
        files={"file": ("big.png", big, "image/png")},
        headers=headers,
    )
    assert r.status_code == 422


async def test_get_my_profile(client, service_headers) -> None:
    _tenant, user, headers = await _make_user(
        client, service_headers, email="p@test.com", ext_id="up1"
    )
    r = await client.get("/api/users/me", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == user["id"]
    assert body["email"] == "p@test.com"
    assert body["role"] == "member"


async def test_patch_my_profile_updates_display_name(client, service_headers) -> None:
    _tenant, _user, headers = await _make_user(
        client, service_headers, email="q@test.com", ext_id="up2"
    )
    r = await client.patch(
        "/api/users/me", json={"display_name": "New Name"}, headers=headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["display_name"] == "New Name"

    me = await client.get("/api/users/me", headers=headers)
    assert me.json()["display_name"] == "New Name"


async def test_patch_my_profile_rejects_blank_name(client, service_headers) -> None:
    _tenant, _user, headers = await _make_user(
        client, service_headers, email="r@test.com", ext_id="up3"
    )
    r = await client.patch(
        "/api/users/me", json={"display_name": "   "}, headers=headers
    )
    assert r.status_code == 422


async def test_get_my_profile_requires_auth(client, service_headers) -> None:
    await _make_user(client, service_headers, email="s@test.com", ext_id="up4")
    r = await client.get("/api/users/me")
    assert r.status_code == 401


async def test_upload_only_affects_own_avatar(client, service_headers) -> None:
    _t1, user_a, headers_a = await _make_user(
        client, service_headers, email="e@test.com", ext_id="u5"
    )
    _t2, user_b, _headers_b = await _make_user(
        client, service_headers, email="f@test.com", ext_id="u6"
    )

    r = await client.post(
        "/api/users/me/avatar",
        files={"file": ("me.png", PNG_BYTES, "image/png")},
        headers=headers_a,
    )
    assert r.status_code == 200

    # User A has an avatar; user B does not (endpoint always targets the caller).
    assert (
        await client.get(f"/api/users/{user_a['id']}/avatar")
    ).status_code == 200
    assert (
        await client.get(f"/api/users/{user_b['id']}/avatar")
    ).status_code == 404
