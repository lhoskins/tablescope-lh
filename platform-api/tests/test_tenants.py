"""Tenant + user CRUD route tests."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.services.supabase_auth_service import SupabaseAuthService, SupabaseUser


@pytest.fixture()
def customer_dir(monkeypatch, tmp_path):
    target = tmp_path / "customers"
    monkeypatch.setenv("CUSTOMER_BASE_PATH", str(target))
    from app.config import get_settings

    get_settings.cache_clear()
    yield target
    if target.exists():
        shutil.rmtree(target)


class _FakeSupabase(SupabaseAuthService):
    """Override only the GoTrue network calls; keep real DB mapping."""

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


@pytest.fixture()
def fake_supabase(monkeypatch):
    """Make user creation go through Supabase (mocked) — there is no local fallback."""
    import app.routes.tenants as tenants_module

    monkeypatch.setattr(tenants_module, "SupabaseAuthService", _FakeSupabase)
    monkeypatch.setattr(tenants_module, "EmailService", _FakeEmail)
    yield


async def test_create_tenant_and_user(
    client, service_headers, customer_dir: Path, fake_supabase
) -> None:
    response = await client.post(
        "/api/tenants",
        json={"slug": "acme", "name": "Acme Co"},
        headers=service_headers,
    )
    assert response.status_code == 201, response.text
    tenant = response.json()
    assert tenant["slug"] == "acme"

    response = await client.post(
        f"/api/tenants/{tenant['id']}/users",
        json={
            "email": "alice@example.com",
            "display_name": "Alice",
            "role": "editor",
        },
        headers=service_headers,
    )
    assert response.status_code == 201, response.text
    user = response.json()
    assert user["email"] == "alice@example.com"
    assert user["tenant_id"] == tenant["id"]

    response = await client.get(
        f"/api/tenants/{tenant['id']}/users",
        headers=service_headers,
    )
    assert response.status_code == 200
    assert len(response.json()) == 1

    assert (customer_dir / "acme").exists()
    assert (customer_dir / "acme" / "users" / "supa-alice@example.com").exists()


async def test_anonymous_cannot_create_tenant(client) -> None:
    response = await client.post(
        "/api/tenants",
        json={"slug": "x", "name": "x"},
    )
    assert response.status_code == 401


async def test_delete_app_tenant_cascades(
    client, service_headers, customer_dir: Path
) -> None:
    created = await client.post(
        "/api/tenants",
        json={
            "slug": "deltest",
            "name": "Delete Test",
            "root_user_email": "admin@deltest.com",
            "root_user_password": "pw-123456",
        },
        headers=service_headers,
    )
    assert created.status_code == 201, created.text
    tenant_id = created.json()["id"]
    assert (customer_dir / "deltest").exists()

    deleted = await client.delete(
        f"/api/tenants/{tenant_id}", headers=service_headers
    )
    assert deleted.status_code == 200, deleted.text
    body = deleted.json()
    assert body["slug"] == "deltest"
    assert body["deleted_rows"]["users"] >= 1
    assert body["deleted_rows"]["tenants"] == 1

    # Tenant is gone from the list.
    listing = await client.get("/api/tenants", headers=service_headers)
    slugs = [t["slug"] for t in listing.json()]
    assert "deltest" not in slugs


async def test_delete_missing_tenant_404(client, service_headers) -> None:
    resp = await client.delete("/api/tenants/999999", headers=service_headers)
    assert resp.status_code == 404


async def test_delete_tenant_bound_to_data_plane_rejected(
    client, service_headers, customer_dir: Path
) -> None:
    # Provision a data plane and bind a new app tenant to it.
    plane = await client.post(
        "/api/tenant-data-planes",
        json={
            "tenant_id": "boundco",
            "tenant_name": "Bound Co",
            "allowed_onprem_cidrs": [],
        },
        headers=service_headers,
    )
    assert plane.status_code == 201, plane.text
    bound = await client.post(
        "/api/tenant-data-planes/boundco/bind-app-tenant",
        json={
            "new_tenant_slug": "boundco",
            "admin_email": "admin@boundco.com",
            "admin_password": "pw-123456",
        },
        headers=service_headers,
    )
    assert bound.status_code == 200, bound.text
    org_id = bound.json()["org_tenant_id"]

    # Deleting via the app-tenant endpoint must be rejected (use data-plane delete).
    rejected = await client.delete(
        f"/api/tenants/{org_id}", headers=service_headers
    )
    assert rejected.status_code == 409
    assert "data plane" in rejected.json()["detail"].lower()


# --- Tenant-wide 2FA enforcement toggle -------------------------------------


def _admin_token(tenant_id: int, user_id: int, aal: str | None = None) -> str:
    from app.auth.jwt import create_access_token

    extra_claims = {"aal": aal} if aal else None
    return create_access_token(
        sub="admin-test",
        tenant_id=tenant_id,
        user_id=user_id,
        role="admin",
        extra_claims=extra_claims,
    )


async def test_tenant_2fa_enforcement_toggle(
    client, service_headers, monkeypatch
) -> None:
    created = await client.post(
        "/api/tenants",
        json={
            "slug": "2fa-toggle",
            "name": "2FA Toggle",
            "root_user_email": "admin@2fa-toggle.com",
            "root_user_password": "pw-123456",
        },
        headers=service_headers,
    )
    assert created.status_code == 201, created.text
    tenant = created.json()
    assert tenant["enforce_2fa"] is False

    # Enabling tenant-wide 2FA now requires Twilio Verify config and an aal2 session.
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC_test")
    monkeypatch.setenv("TWILIO_API_KEY_SID", "SK_test")
    monkeypatch.setenv("TWILIO_API_KEY_SECRET", "secret")
    monkeypatch.setenv("TWILIO_VERIFY_SERVICE_SID", "VA_test")
    from app.config import get_settings

    get_settings.cache_clear()

    headers = {"Authorization": f"Bearer {_admin_token(tenant['id'], 1, aal='aal2')}"}
    r = await client.put(
        f"/api/tenants/{tenant['id']}/2fa-enforcement",
        json={"enabled": True},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is True

    r = await client.get(
        f"/api/tenants/{tenant['id']}/2fa-enforcement",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is True
