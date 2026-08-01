"""Settings workspace API tests."""

from __future__ import annotations

import pytest

from app.auth.jwt import create_access_token
from app.config import get_settings
from app.models.user import User
from app.schemas.tenant import TenantSettingsRead
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


@pytest.fixture()
def fake_supabase(monkeypatch):
    import app.routes.tenants as tenants_module

    monkeypatch.setattr(tenants_module, "SupabaseAuthService", _FakeSupabase)
    yield


async def _create_tenant_with_root(client, service_headers, fake_supabase):
    r = await client.post(
        "/api/tenants",
        json={
            "slug": "settings-test",
            "name": "Settings Test",
            "root_user_email": "admin@settings-test.com",
            "root_user_password": "pw-123456",
        },
        headers=service_headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _headers(
    tenant_id: int, user_id: int, role: str = "admin", aal: str | None = None
) -> dict:
    extra_claims = {"aal": aal} if aal is not None else None
    return {
        "Authorization": "Bearer "
        + create_access_token(
            sub=f"u{user_id}",
            tenant_id=tenant_id,
            user_id=user_id,
            role=role,
            extra_claims=extra_claims,
        )
    }


async def test_current_tenant_settings_safe(client, service_headers, fake_supabase) -> None:
    tenant = await _create_tenant_with_root(client, service_headers, fake_supabase)
    headers = _headers(tenant["id"], 1)

    r = await client.get("/api/tenants/current/settings", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()

    # Safe fields are present.
    assert data["id"] == tenant["id"]
    assert data["name"] == tenant["name"]
    assert data["slug"] == tenant["slug"]
    assert "enforce_2fa" in data
    assert "login_url" in data

    # Sensitive fields are not exposed.
    assert "users" not in data
    assert "shared_vdbs" not in data
    assert "documents" not in data
    assert "vdb" not in data

    # Response matches the safe settings schema.
    assert set(TenantSettingsRead.model_fields.keys()).issuperset(data.keys())


async def test_current_tenant_settings_rejects_cross_tenant(
    client, service_headers, fake_supabase, db_session
) -> None:
    tenant_a = await _create_tenant_with_root(client, service_headers, fake_supabase)
    tenant_b = await client.post(
        "/api/tenants",
        json={
            "slug": "settings-test-b",
            "name": "Settings Test B",
            "root_user_email": "admin@settings-test-b.com",
            "root_user_password": "pw-123456",
        },
        headers=service_headers,
    )
    assert tenant_b.status_code == 201, tenant_b.text
    tenant_b = tenant_b.json()

    # User 1 from tenant A should not be able to read tenant B settings.
    headers = _headers(tenant_a["id"], 1)
    r = await client.get("/api/tenants/current/settings", headers=headers)
    assert r.status_code == 200
    assert r.json()["id"] == tenant_a["id"]
    assert r.json()["id"] != tenant_b["id"]


async def test_tenant_details_restricted_to_root_or_super(
    client, service_headers, fake_supabase, db_session
) -> None:
    tenant = await _create_tenant_with_root(client, service_headers, fake_supabase)
    admin_headers = _headers(tenant["id"], 1, "admin")

    # Plain tenant admin should not see users / VDB details.
    r = await client.get(f"/api/tenants/{tenant['id']}/details", headers=admin_headers)
    assert r.status_code == 403, r.text

    # Super admin can.
    user = await db_session.get(User, 1)
    user.is_super_admin = True
    await db_session.commit()

    r = await client.get(f"/api/tenants/{tenant['id']}/details", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert "users" in r.json()
    assert "shared_vdbs" in r.json()


async def test_current_2fa_toggle_and_audit(
    client, service_headers, fake_supabase, db_session, monkeypatch
) -> None:
    tenant = await _create_tenant_with_root(client, service_headers, fake_supabase)
    # Enabling tenant-wide 2FA now requires Twilio Verify config and an aal2 session.
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC_test")
    monkeypatch.setenv("TWILIO_API_KEY_SID", "SK_test")
    monkeypatch.setenv("TWILIO_API_KEY_SECRET", "secret")
    monkeypatch.setenv("TWILIO_VERIFY_SERVICE_SID", "VA_test")
    get_settings.cache_clear()
    headers = _headers(tenant["id"], 1, "admin", aal="aal2")

    r = await client.get("/api/tenants/current/2fa-enforcement", headers=headers)
    assert r.status_code == 200
    initial = r.json()["enabled"]

    r = await client.put(
        "/api/tenants/current/2fa-enforcement",
        json={"enabled": not initial},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is not initial


async def test_enable_2fa_requires_twilio_config(
    client, service_headers, fake_supabase, monkeypatch
) -> None:
    tenant = await _create_tenant_with_root(client, service_headers, fake_supabase)
    # Ensure Twilio Verify appears unconfigured.
    monkeypatch.delenv("TWILIO_VERIFY_SERVICE_SID", raising=False)
    get_settings.cache_clear()
    headers = _headers(tenant["id"], 1, "admin", aal="aal2")

    r = await client.put(
        "/api/tenants/current/2fa-enforcement",
        json={"enabled": True},
        headers=headers,
    )
    assert r.status_code == 503, r.text
    assert "SMS provider is not configured" in r.json()["detail"]


async def test_enable_2fa_requires_aal2(
    client, service_headers, fake_supabase, monkeypatch
) -> None:
    tenant = await _create_tenant_with_root(client, service_headers, fake_supabase)
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC_test")
    monkeypatch.setenv("TWILIO_API_KEY_SID", "SK_test")
    monkeypatch.setenv("TWILIO_API_KEY_SECRET", "secret")
    monkeypatch.setenv("TWILIO_VERIFY_SERVICE_SID", "VA_test")
    get_settings.cache_clear()
    headers = _headers(tenant["id"], 1, "admin", aal="aal1")

    r = await client.put(
        "/api/tenants/current/2fa-enforcement",
        json={"enabled": True},
        headers=headers,
    )
    assert r.status_code == 409, r.text
    assert "step-up authentication" in r.json()["detail"]


async def test_current_reprocess_documents_scoped(
    client, service_headers, fake_supabase
) -> None:
    tenant = await _create_tenant_with_root(client, service_headers, fake_supabase)
    headers = _headers(tenant["id"], 1, "admin")

    r = await client.post(
        "/api/tenants/current/reprocess-documents?force=false",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["tenant_id"] == tenant["id"]
    assert data["status"] == "queued"


async def test_unauthorized_roles_blocked_from_settings(
    client, service_headers, fake_supabase
) -> None:
    tenant = await _create_tenant_with_root(client, service_headers, fake_supabase)
    # Create an editor user.
    r = await client.post(
        f"/api/tenants/{tenant['id']}/users",
        json={"email": "editor@settings-test.com", "role": "editor"},
        headers=service_headers,
    )
    assert r.status_code == 201, r.text
    user = r.json()
    editor_headers = _headers(tenant["id"], user["id"], "editor")

    r = await client.get("/api/tenants/current/settings", headers=editor_headers)
    assert r.status_code == 403

    r = await client.put(
        "/api/tenants/current/2fa-enforcement",
        json={"enabled": True},
        headers=editor_headers,
    )
    assert r.status_code == 403
