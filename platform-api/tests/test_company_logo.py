"""Tests for admin company-logo upload + serving (tenant branding)."""

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


async def _make_tenant_with_users(client, service_headers, *, slug):
    r = await client.post(
        "/api/tenants",
        json={"slug": slug, "name": "Logo Tenant"},
        headers=service_headers,
    )
    assert r.status_code == 201, r.text
    tenant = r.json()

    async def _user(email, role, ext_id):
        r = await client.post(
            f"/api/tenants/{tenant['id']}/users",
            json={
                "email": email,
                "display_name": "U",
                "role": role,
                "external_id": ext_id,
            },
            headers=service_headers,
        )
        assert r.status_code == 201, r.text
        user = r.json()
        token = create_access_token(
            sub=ext_id, tenant_id=tenant["id"], user_id=user["id"], role=role
        )
        return user, {"Authorization": f"Bearer {token}"}

    admin, admin_headers = await _user(
        f"admin-{slug}@test.com", "admin", f"adm-{slug}"
    )
    member, member_headers = await _user(
        f"member-{slug}@test.com", "member", f"mem-{slug}"
    )
    return tenant, (admin, admin_headers), (member, member_headers)


async def test_admin_can_upload_company_logo(client, service_headers) -> None:
    tenant, (_admin, admin_headers), _member = await _make_tenant_with_users(
        client, service_headers, slug="logo-a"
    )

    r = await client.post(
        "/api/tenants/current/logo",
        files={"file": ("logo.png", PNG_BYTES, "image/png")},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["logo_url"].startswith(f"/api/tenants/{tenant['id']}/logo")
    # No raw filesystem path is exposed.
    assert "/tmp" not in body["logo_url"]
    assert "customers" not in body["logo_url"]

    # /auth/me now carries the company logo URL for the app shell.
    me = await client.get("/api/auth/me", headers=admin_headers)
    assert me.status_code == 200
    assert me.json()["company_logo_url"] == body["logo_url"]

    # The image is served by the opaque URL (no auth needed for <img>).
    img = await client.get(f"/api/tenants/{tenant['id']}/logo")
    assert img.status_code == 200
    assert img.headers["content-type"] == "image/png"
    assert img.content == PNG_BYTES


async def test_member_cannot_upload_company_logo(client, service_headers) -> None:
    _tenant, _admin, (_member, member_headers) = await _make_tenant_with_users(
        client, service_headers, slug="logo-b"
    )
    r = await client.post(
        "/api/tenants/current/logo",
        files={"file": ("logo.png", PNG_BYTES, "image/png")},
        headers=member_headers,
    )
    assert r.status_code == 403


async def test_unauthenticated_upload_rejected(client, service_headers) -> None:
    await _make_tenant_with_users(client, service_headers, slug="logo-c")
    r = await client.post(
        "/api/tenants/current/logo",
        files={"file": ("logo.png", PNG_BYTES, "image/png")},
    )
    assert r.status_code == 401


async def test_invalid_file_type_rejected(client, service_headers) -> None:
    _tenant, (_admin, admin_headers), _member = await _make_tenant_with_users(
        client, service_headers, slug="logo-d"
    )
    r = await client.post(
        "/api/tenants/current/logo",
        files={"file": ("x.svg", b"<svg></svg>", "image/svg+xml")},
        headers=admin_headers,
    )
    assert r.status_code == 422


async def test_member_can_read_current_logo(client, service_headers) -> None:
    tenant, (_admin, admin_headers), (_member, member_headers) = (
        await _make_tenant_with_users(client, service_headers, slug="logo-e")
    )
    # No logo yet.
    r = await client.get("/api/tenants/current/logo", headers=member_headers)
    assert r.status_code == 200
    assert r.json()["logo_url"] is None

    await client.post(
        "/api/tenants/current/logo",
        files={"file": ("logo.png", PNG_BYTES, "image/png")},
        headers=admin_headers,
    )
    r = await client.get("/api/tenants/current/logo", headers=member_headers)
    assert r.status_code == 200
    assert r.json()["logo_url"].startswith(f"/api/tenants/{tenant['id']}/logo")


async def test_logo_isolated_per_tenant(client, service_headers) -> None:
    t1, (_a1, admin1), _m1 = await _make_tenant_with_users(
        client, service_headers, slug="logo-f"
    )
    t2, _a2, _m2 = await _make_tenant_with_users(
        client, service_headers, slug="logo-g"
    )

    r = await client.post(
        "/api/tenants/current/logo",
        files={"file": ("logo.png", PNG_BYTES, "image/png")},
        headers=admin1,
    )
    assert r.status_code == 200

    # Tenant 1 has a logo; tenant 2 does not (upload always targets the caller).
    assert (await client.get(f"/api/tenants/{t1['id']}/logo")).status_code == 200
    assert (await client.get(f"/api/tenants/{t2['id']}/logo")).status_code == 404
