"""TS-ISO-015: password login without a tenant_slug must not silently pick
an arbitrary account when the same email exists in more than one tenant --
email is unique per-tenant, not globally.

Run from ``platform-api``: ``pytest -q tests/test_login_tenant_ambiguity.py``.
"""

from __future__ import annotations

import pytest

from app.models.user import User

pytestmark = pytest.mark.anyio


async def _tenant(client, service_headers, slug: str) -> int:
    r = await client.post(
        "/api/tenants", json={"slug": slug, "name": f"{slug} tenant"}, headers=service_headers
    )
    assert r.status_code == 201
    return r.json()["id"]


async def test_ambiguous_email_across_tenants_is_rejected_without_a_slug(
    client, db_session, service_headers
):
    tenant_a = await _tenant(client, service_headers, "login-amb-a")
    tenant_b = await _tenant(client, service_headers, "login-amb-b")

    user_a = User(tenant_id=tenant_a, email="dupe@example.com", display_name="A", role="editor")
    user_a.set_password("password-a")
    user_b = User(tenant_id=tenant_b, email="dupe@example.com", display_name="B", role="editor")
    user_b.set_password("password-b")
    db_session.add_all([user_a, user_b])
    await db_session.commit()

    r = await client.post(
        "/api/auth/login", json={"email": "dupe@example.com", "password": "password-a"}
    )
    assert r.status_code == 400
    assert "organization" in r.json()["detail"].lower()


async def test_ambiguous_email_with_explicit_slug_succeeds(
    client, db_session, service_headers
):
    tenant_a = await _tenant(client, service_headers, "login-slug-a")
    tenant_b = await _tenant(client, service_headers, "login-slug-b")

    user_a = User(tenant_id=tenant_a, email="dupe2@example.com", display_name="A", role="editor")
    user_a.set_password("password-a")
    user_b = User(tenant_id=tenant_b, email="dupe2@example.com", display_name="B", role="editor")
    user_b.set_password("password-b")
    db_session.add_all([user_a, user_b])
    await db_session.commit()

    r = await client.post(
        "/api/auth/login",
        json={"email": "dupe2@example.com", "password": "password-a", "tenant_slug": "login-slug-a"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["tenant_id"] == tenant_a


async def test_unique_email_without_a_slug_still_works(client, db_session, service_headers):
    tenant_id = await _tenant(client, service_headers, "login-unique")
    user = User(tenant_id=tenant_id, email="solo@example.com", display_name="Solo", role="editor")
    user.set_password("password-solo")
    db_session.add(user)
    await db_session.commit()

    r = await client.post(
        "/api/auth/login", json={"email": "solo@example.com", "password": "password-solo"}
    )
    assert r.status_code == 200, r.text
