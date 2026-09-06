"""Tests for the two-step "verify email before sending credentials" gate.

Covers:
1. Token round-trip: create -> consume marks the user verified.
2. An unknown token is rejected.
3. An expired token is rejected.
4. Consuming an already-verified user's token twice reports already_verified.
5. Tenant-user invite: POST /tenants/{id}/users sends only account_confirmation
   (no Supabase call, no login credentials) and creates an unverified user.
6. POST /api/auth/verify-email completes the invite: creates the Supabase
   identity, sends the real "set your password" email, and marks the user
   verified.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.auth.jwt import create_access_token
from app.models.email_verification_token import EmailVerificationToken
from app.models.tenant import Tenant
from app.models.user import User
from app.services.email_verification_service import (
    TENANT_ADMIN_INVITE,
    USER_INVITE,
    VerificationTokenError,
    consume_verification_token,
    create_verification_token,
)
from app.services.supabase_auth_service import SupabaseAuthService, SupabaseUser

pytestmark = pytest.mark.anyio


async def _tenant_user(db_session, slug: str) -> tuple[Tenant, User]:
    tenant = Tenant(slug=slug, name=f"{slug} tenant", is_active=True)
    db_session.add(tenant)
    await db_session.flush()
    user = User(
        tenant_id=tenant.id,
        email=f"{slug}@test.com",
        display_name="Test User",
        role="editor",
    )
    db_session.add(user)
    await db_session.flush()
    return tenant, user


# ── 1-4: service-level token lifecycle ──────────────────────────────────


async def test_verification_round_trip_marks_user_verified(db_session):
    tenant, user = await _tenant_user(db_session, "vrt")
    await db_session.commit()

    raw_token = await create_verification_token(
        db_session, tenant_id=tenant.id, user_id=user.id, purpose=USER_INVITE
    )
    await db_session.commit()
    assert user.email_verified is False

    result = await consume_verification_token(db_session, raw_token)
    await db_session.commit()

    assert result.already_verified is False
    assert result.purpose == USER_INVITE
    await db_session.refresh(user)
    assert user.email_verified is True
    assert user.email_verified_at is not None


async def test_unknown_token_is_rejected(db_session):
    with pytest.raises(VerificationTokenError):
        await consume_verification_token(db_session, "not-a-real-token")


async def test_expired_token_is_rejected(db_session):
    tenant, user = await _tenant_user(db_session, "expired")
    await db_session.commit()

    raw_token = await create_verification_token(
        db_session, tenant_id=tenant.id, user_id=user.id, purpose=USER_INVITE
    )
    row = await db_session.scalar(
        select(EmailVerificationToken).where(
            EmailVerificationToken.user_id == user.id
        )
    )
    row.expires_at = datetime.now(UTC) - timedelta(hours=1)
    await db_session.commit()

    with pytest.raises(VerificationTokenError):
        await consume_verification_token(db_session, raw_token)


async def test_consuming_twice_reports_already_verified(db_session):
    tenant, user = await _tenant_user(db_session, "double")
    await db_session.commit()

    raw_token = await create_verification_token(
        db_session, tenant_id=tenant.id, user_id=user.id, purpose=TENANT_ADMIN_INVITE
    )
    await db_session.commit()

    first = await consume_verification_token(db_session, raw_token)
    await db_session.commit()
    assert first.already_verified is False

    second = await consume_verification_token(db_session, raw_token)
    assert second.already_verified is True
    assert second.user.id == user.id


# ── 5-6: route-level invite flow ────────────────────────────────────────


class _FakeSupabase(SupabaseAuthService):
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def create_or_invite_user(
        self, email, *, first_name=None, last_name=None, redirect_to=None
    ) -> SupabaseUser:
        self.calls.append(email)
        return SupabaseUser(
            id=f"supa-{email}", email=email, created=True, action_link=f"https://invite/{email}"
        )


class _FakeEmail:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.calls: list[dict] = []

    async def send_transactional_email(
        self, *, to, template, variables, subject=None, reply_to=None, tenant_id=None
    ) -> bool:
        self.sent.append((to, template))
        self.calls.append({"to": to, "template": template, "variables": variables})
        return True


@pytest_asyncio.fixture
def fake_supabase(monkeypatch):
    import app.routes.auth as auth_module
    import app.routes.tenants_users as tenants_module

    supa = _FakeSupabase()
    email = _FakeEmail()
    monkeypatch.setattr(tenants_module, "SupabaseAuthService", lambda: supa)
    monkeypatch.setattr(tenants_module, "EmailService", lambda: email)
    monkeypatch.setattr(auth_module, "send_transactional_email", email.send_transactional_email)
    return supa, email


def _editor_headers(tenant_id: int, user_id: int) -> dict:
    token = create_access_token(sub="u", tenant_id=tenant_id, user_id=user_id, role="editor")
    return {"Authorization": f"Bearer {token}"}


async def test_invite_sends_only_confirmation_no_credentials_yet(
    client, service_headers, fake_supabase
):
    supa, email = fake_supabase

    r = await client.post(
        "/api/tenants",
        json={"slug": "verify-co", "name": "Verify Co"},
        headers=service_headers,
    )
    assert r.status_code == 201
    tenant_id = r.json()["id"]

    r = await client.post(
        f"/api/tenants/{tenant_id}/users",
        json={"email": "bob@verify-co.com", "display_name": "Bob", "role": "editor"},
        headers=service_headers,
    )
    assert r.status_code == 201, r.text
    user = r.json()
    assert user["email"] == "bob@verify-co.com"

    # No Supabase identity created yet, and only the confirmation email sent.
    assert supa.calls == []
    assert ("bob@verify-co.com", "account_confirmation") in email.sent
    assert not any(t == "user_invitation" for _, t in email.sent)


async def test_verify_email_completes_user_invitation(
    client, service_headers, fake_supabase, db_session
):
    supa, email = fake_supabase

    r = await client.post(
        "/api/tenants",
        json={"slug": "verify-co2", "name": "Verify Co 2"},
        headers=service_headers,
    )
    tenant_id = r.json()["id"]

    r = await client.post(
        f"/api/tenants/{tenant_id}/users",
        json={"email": "carol@verify-co2.com", "display_name": "Carol", "role": "editor"},
        headers=service_headers,
    )
    user_id = r.json()["id"]

    call = next(c for c in email.calls if c["template"] == "account_confirmation")
    confirmation_link = call["variables"]["confirmation_link"]
    raw_token = confirmation_link.split("token=", 1)[1]

    r = await client.post("/api/auth/verify-email", json={"token": raw_token})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "carol@verify-co2.com"
    assert body["already_verified"] is False

    assert supa.calls == ["carol@verify-co2.com"]
    assert ("carol@verify-co2.com", "user_invitation") in email.sent

    user = await db_session.get(User, user_id)
    assert user.email_verified is True
    assert user.supabase_user_id == "supa-carol@verify-co2.com"
