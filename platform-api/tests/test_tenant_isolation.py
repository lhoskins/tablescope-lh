"""Tenant-membership isolation tests (Issue 6).

Supabase identity is global, but Tablescope access is scoped per tenant: a token
is only honoured while the caller is an active member of the token's tenant.
"""

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
def _mock_externals(monkeypatch):
    import app.routes.tenants_users as tenants_module

    monkeypatch.setattr(tenants_module, "SupabaseAuthService", _FakeSupabase)
    monkeypatch.setattr(tenants_module, "EmailService", _FakeEmail)


async def _make_tenant(client_strict, service_headers, slug):
    r = await client_strict.post(
        "/api/tenants",
        json={"slug": slug, "name": slug.title()},
        headers=service_headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _make_user(client_strict, service_headers, tenant_id, email, ext_id, role="member"):
    r = await client_strict.post(
        f"/api/tenants/{tenant_id}/users",
        json={
            "email": email,
            "display_name": "U",
            "role": role,
            "external_id": ext_id,
        },
        headers=service_headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _headers(tenant_id, user_id, role="member", sub="ext", aal=None):
    return {
        "Authorization": "Bearer "
        + create_access_token(
            sub=sub,
            tenant_id=tenant_id,
            user_id=user_id,
            role=role,
            extra_claims={"aal": aal} if aal is not None else None,
        )
    }


async def test_non_member_token_is_forbidden(client_strict, service_headers) -> None:
    tenant = await _make_tenant(client_strict, service_headers, "iso-a")
    # A token for a user_id that has no membership row in this tenant.
    r = await client_strict.get(
        "/api/auth/me", headers=_headers(tenant["id"], 999999)
    )
    assert r.status_code == 403


async def test_cross_tenant_token_is_forbidden(client_strict, service_headers) -> None:
    tenant_a = await _make_tenant(client_strict, service_headers, "iso-x")
    tenant_b = await _make_tenant(client_strict, service_headers, "iso-y")
    user_a = await _make_user(
        client_strict, service_headers, tenant_a["id"], "a@test.com", "ext-a"
    )
    # The user's real id, but a token claiming tenant B (where they have no row).
    r = await client_strict.get(
        "/api/auth/me",
        headers=_headers(tenant_b["id"], user_a["id"]),
    )
    assert r.status_code == 403


async def test_same_email_two_tenants_are_independent(
    client_strict, service_headers
) -> None:
    tenant_a = await _make_tenant(client_strict, service_headers, "iso-1")
    tenant_b = await _make_tenant(client_strict, service_headers, "iso-2")
    # Same email + supabase identity, separate membership rows per tenant.
    user_a = await _make_user(
        client_strict, service_headers, tenant_a["id"], "dup@test.com", "ext-dup"
    )
    user_b = await _make_user(
        client_strict, service_headers, tenant_b["id"], "dup@test.com", "ext-dup"
    )
    assert user_a["id"] != user_b["id"]

    # Deactivate the Tenant A membership.
    r = await client_strict.put(
        f"/api/tenants/{tenant_a['id']}/users/{user_a['id']}",
        json={"is_active": False},
        headers=service_headers,
    )
    assert r.status_code == 200, r.text

    # Tenant A access is now blocked...
    r = await client_strict.get(
        "/api/auth/me", headers=_headers(tenant_a["id"], user_a["id"])
    )
    assert r.status_code == 403
    # ...but the Tenant B membership is untouched.
    r = await client_strict.get(
        "/api/auth/me", headers=_headers(tenant_b["id"], user_b["id"])
    )
    assert r.status_code == 200, r.text
    assert r.json()["tenant_id"] == tenant_b["id"]


async def test_inactive_member_is_forbidden(client_strict, service_headers) -> None:
    tenant = await _make_tenant(client_strict, service_headers, "iso-inact")
    user = await _make_user(
        client_strict, service_headers, tenant["id"], "z@test.com", "ext-z"
    )
    r = await client_strict.put(
        f"/api/tenants/{tenant['id']}/users/{user['id']}",
        json={"is_active": False},
        headers=service_headers,
    )
    assert r.status_code == 200
    r = await client_strict.get(
        "/api/auth/me", headers=_headers(tenant["id"], user["id"])
    )
    assert r.status_code == 403


async def test_role_resolved_from_membership_not_token(
    client_strict, service_headers
) -> None:
    """A token claiming admin for a member-role row is gated to the DB role."""
    tenant = await _make_tenant(client_strict, service_headers, "iso-role")
    admin = await _make_user(
        client_strict, service_headers, tenant["id"], "admin@test.com", "ext-adm", "admin"
    )
    member = await _make_user(
        client_strict, service_headers, tenant["id"], "m@test.com", "ext-m", "member"
    )
    # Forge an admin-role token for the member.
    forged = _headers(tenant["id"], member["id"], role="admin", sub="ext-m")
    # Listing allowed domains requires admin; the DB role (member) must win.
    r = await client_strict.get(
        "/api/tenants/current/allowed-domains", headers=forged
    )
    assert r.status_code == 403

    # The genuine admin can (admin routes require an aal2 / MFA-satisfied session).
    good = _headers(tenant["id"], admin["id"], role="admin", sub="ext-adm", aal="aal2")
    r = await client_strict.get("/api/tenants/current/allowed-domains", headers=good)
    assert r.status_code == 200, r.text
