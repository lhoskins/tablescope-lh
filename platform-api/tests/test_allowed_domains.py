"""Tests for tenant Allowed-Domains: service rules, API, and enforcement."""

from __future__ import annotations

import pytest

from app.auth.jwt import create_access_token
from app.services.allowed_domains import (
    email_domain,
    is_valid_domain,
    normalize_domain,
    normalize_email_domain,
)
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
    async def send_transactional_email(self, *, to, template, variables, **kw) -> bool:
        return True


@pytest.fixture(autouse=True)
def _mock_supabase(monkeypatch):
    import app.routes.tenants as tenants_module

    monkeypatch.setattr(tenants_module, "SupabaseAuthService", _FakeSupabase)
    monkeypatch.setattr(tenants_module, "EmailService", _FakeEmail)


# ---------------------------------------------------------------------------
# Pure helper tests
# ---------------------------------------------------------------------------


def test_email_domain_lowercases_and_strips() -> None:
    assert email_domain("Alice@Boeing.COM") == "boeing.com"
    assert email_domain("bob@safran-group.com ") == "safran-group.com"


def test_normalize_email_domain() -> None:
    assert normalize_email_domain("Leonard.Hoskins@SafranGroup.com") == "safrangroup.com"
    assert normalize_email_domain("a@b.com ") == "b.com"


def test_normalize_domain() -> None:
    assert normalize_domain("  Boeing.com ") == "boeing.com"
    assert normalize_domain("@tablescope.ai") == "tablescope.ai"


def test_is_valid_domain() -> None:
    assert is_valid_domain("boeing.com")
    assert is_valid_domain("safran-group.com")
    assert is_valid_domain("sub.tablescope.ai")
    # Invalid / wildcards rejected.
    assert not is_valid_domain("*.boeing.com")
    assert not is_valid_domain("boeing")
    assert not is_valid_domain("user@boeing.com")
    assert not is_valid_domain("")
    assert not is_valid_domain("bad domain.com")


# ---------------------------------------------------------------------------
# Service enforcement (uses a live session)
# ---------------------------------------------------------------------------


async def _make_tenant_with_owner(session):
    from app.models.tenant import Tenant, TenantAllowedDomain
    from app.models.user import User

    tenant = Tenant(slug="acme", name="Acme")
    session.add(tenant)
    await session.flush()
    owner = User(
        tenant_id=tenant.id,
        email="owner@external.com",
        role="admin",
    )
    member = User(
        tenant_id=tenant.id,
        email="member@external.com",
        role="member",
    )
    session.add_all([owner, member])
    await session.flush()
    tenant.owner_user_id = owner.id
    tenant.allowed_domains_enabled = True
    session.add(TenantAllowedDomain(tenant_id=tenant.id, domain="boeing.com"))
    await session.flush()
    return tenant, owner, member


async def test_disabled_allows_any_domain(db_session) -> None:
    from app.models.tenant import Tenant
    from app.services.allowed_domains import is_email_allowed_for_tenant

    tenant = Tenant(slug="open", name="Open")
    db_session.add(tenant)
    await db_session.flush()
    assert await is_email_allowed_for_tenant(
        db_session, tenant_id=tenant.id, email="anyone@whatever.io"
    )


async def test_enabled_allows_listed_denies_unlisted(db_session) -> None:
    from app.services.allowed_domains import is_email_allowed_for_tenant

    tenant, _owner, _member = await _make_tenant_with_owner(db_session)
    assert await is_email_allowed_for_tenant(
        db_session, tenant_id=tenant.id, email="pilot@boeing.com"
    )
    # Case-insensitive match.
    assert await is_email_allowed_for_tenant(
        db_session, tenant_id=tenant.id, email="Pilot@BOEING.com"
    )
    assert not await is_email_allowed_for_tenant(
        db_session, tenant_id=tenant.id, email="x@gmail.com"
    )


async def test_enforce_allowed_domain_raises_for_unapproved(db_session) -> None:
    from fastapi import HTTPException

    from app.services.allowed_domains import enforce_allowed_domain

    tenant, owner, _member = await _make_tenant_with_owner(db_session)
    # Unapproved domain (the Safran case from the plan) is blocked on signup.
    with pytest.raises(HTTPException) as exc:
        await enforce_allowed_domain(
            db_session,
            tenant_id=tenant.id,
            email="leonard.hoskins@safrangroup.com",
            purpose="signup",
        )
    assert exc.value.status_code == 403
    # Owner is never locked out, even with a disallowed domain.
    await enforce_allowed_domain(
        db_session, tenant_id=tenant.id, email=owner.email, user_id=owner.id
    )
    # Approved domain passes.
    await enforce_allowed_domain(
        db_session, tenant_id=tenant.id, email="pilot@boeing.com"
    )


async def test_owner_and_admin_exempt(db_session) -> None:
    from app.services.allowed_domains import is_email_allowed_for_tenant

    tenant, owner, _member = await _make_tenant_with_owner(db_session)
    # Owner is exempt even with a disallowed domain.
    assert await is_email_allowed_for_tenant(
        db_session,
        tenant_id=tenant.id,
        email=owner.email,
        user_id=owner.id,
    )


# ---------------------------------------------------------------------------
# API + invite enforcement
# ---------------------------------------------------------------------------


async def _setup_admin(client, service_headers):
    r = await client.post(
        "/api/tenants",
        json={"slug": "dom-tenant", "name": "Domain Tenant"},
        headers=service_headers,
    )
    assert r.status_code == 201
    tenant = r.json()
    r = await client.post(
        f"/api/tenants/{tenant['id']}/users",
        json={
            "email": "admin@boeing.com",
            "display_name": "Admin",
            "role": "admin",
            "external_id": "ext-admin",
        },
        headers=service_headers,
    )
    assert r.status_code == 201
    admin = r.json()
    token = create_access_token(
        sub="admin", tenant_id=tenant["id"], user_id=admin["id"], role="admin"
    )
    return tenant, admin, {"Authorization": f"Bearer {token}"}


async def test_allowed_domains_api_and_invite_enforcement(
    client, service_headers
) -> None:
    tenant, _admin, headers = await _setup_admin(client, service_headers)

    # Initially disabled, empty list.
    r = await client.get("/api/tenants/current/allowed-domains", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json() == {"enabled": False, "domains": []}

    # Enable + add a domain.
    r = await client.put(
        "/api/tenants/current/allowed-domains/settings",
        json={"enabled": True},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["enabled"] is True

    r = await client.post(
        "/api/tenants/current/allowed-domains",
        json={"domain": "Boeing.com"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    domain_id = r.json()["id"]
    assert r.json()["domain"] == "boeing.com"

    # Duplicate rejected.
    r = await client.post(
        "/api/tenants/current/allowed-domains",
        json={"domain": "boeing.com"},
        headers=headers,
    )
    assert r.status_code == 409

    # Invalid domain rejected.
    r = await client.post(
        "/api/tenants/current/allowed-domains",
        json={"domain": "*.boeing.com"},
        headers=headers,
    )
    assert r.status_code == 422

    # Inviting a disallowed domain is blocked.
    r = await client.post(
        f"/api/tenants/{tenant['id']}/users",
        json={"email": "evil@gmail.com", "role": "member", "external_id": "x1"},
        headers=service_headers,
    )
    assert r.status_code == 403

    # Inviting an allowed domain works.
    r = await client.post(
        f"/api/tenants/{tenant['id']}/users",
        json={"email": "pilot@boeing.com", "role": "member", "external_id": "x2"},
        headers=service_headers,
    )
    assert r.status_code == 201, r.text

    # Removing the domain works.
    r = await client.delete(
        f"/api/tenants/current/allowed-domains/{domain_id}", headers=headers
    )
    assert r.status_code == 204


async def test_adding_domain_auto_enables_enforcement(
    client, service_headers
) -> None:
    tenant, _admin, headers = await _setup_admin(client, service_headers)

    # Starts disabled.
    r = await client.get("/api/tenants/current/allowed-domains", headers=headers)
    assert r.json()["enabled"] is False

    # Adding the first domain turns enforcement on automatically.
    r = await client.post(
        "/api/tenants/current/allowed-domains",
        json={"domain": "boeing.com"},
        headers=headers,
    )
    assert r.status_code == 201, r.text

    r = await client.get("/api/tenants/current/allowed-domains", headers=headers)
    assert r.json()["enabled"] is True

    # A disallowed domain is now blocked without any explicit toggle step.
    r = await client.post(
        f"/api/tenants/{tenant['id']}/users",
        json={
            "email": "leonard.hoskins@safrangroup.com",
            "role": "member",
            "external_id": "safran-1",
        },
        headers=service_headers,
    )
    assert r.status_code == 403, r.text


async def test_allowed_domains_requires_admin(client, service_headers) -> None:
    tenant, _admin, _headers = await _setup_admin(client, service_headers)
    member = create_access_token(
        sub="m", tenant_id=tenant["id"], user_id=999, role="member"
    )
    r = await client.get(
        "/api/tenants/current/allowed-domains",
        headers={"Authorization": f"Bearer {member}"},
    )
    assert r.status_code == 403


async def test_email_service_suppresses_disallowed_domain(
    db_engine, monkeypatch
) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    import app.database as database_module
    from app.services.email_service import EmailService

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    # EmailService opens its own session via app.database.SessionLocal; bind it to
    # the test engine so the tenant policy is visible.
    monkeypatch.setattr(database_module, "SessionLocal", factory)

    async with factory() as session:
        tenant, _owner, _member = await _make_tenant_with_owner(session)
        tenant_id = tenant.id
        await session.commit()

    svc = EmailService()
    # Disallowed recipient: suppressed (returns False, never sends).
    sent = await svc.send_transactional_email(
        to="x@gmail.com",
        template="user_invitation",
        variables={},
        tenant_id=tenant_id,
    )
    assert sent is False
