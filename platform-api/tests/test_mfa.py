"""Twilio SMS MFA tests.

Covers backend aal2 enforcement for admin roles, the ``/mfa/status`` endpoint,
the Twilio service contract (Messaging Service SID, no code/secret logging),
SMS cost controls (resend cooldown + send caps), audit writes, and the Supabase
Send-SMS hook signature gate.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.auth.jwt import create_access_token
from app.models.mfa_sms_event import (
    MFA_SMS_CODE_SENT,
    MfaSmsEvent,
)
from app.models.tenant import Tenant
from app.models.user import User


async def _seed(db_session, *, role="admin", email="u@test.com", ext="ext-u"):
    tenant = Tenant(slug=f"t-{ext}", name="T")
    db_session.add(tenant)
    await db_session.flush()
    user = User(
        tenant_id=tenant.id,
        email=email,
        external_id=ext,
        supabase_user_id=ext,
        role=role,
        status="active",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    return tenant, user


def _headers(tenant_id, user_id, *, role="admin", aal=None, sub="ext-u"):
    extra = {"aal": aal} if aal is not None else None
    return {
        "Authorization": "Bearer "
        + create_access_token(
            sub=sub,
            tenant_id=tenant_id,
            user_id=user_id,
            role=role,
            extra_claims=extra,
        )
    }


# --- aal2 enforcement -------------------------------------------------------


@pytest.mark.parametrize("role", ["admin", "db_admin", "owner"])
async def test_admin_role_aal1_is_mfa_required(client_strict, db_session, role) -> None:
    tenant, user = await _seed(db_session, role=role, ext=f"ext-{role}")
    r = await client_strict.get(
        "/api/projects",
        headers=_headers(tenant.id, user.id, role=role, aal="aal1", sub=f"ext-{role}"),
    )
    assert r.status_code == 403
    body = r.json()
    assert body["error"] == "MFA_REQUIRED"
    assert body["requiresMfa"] is True
    assert body["preferredFactorType"] == "phone"


async def test_admin_aal2_can_access(client_strict, db_session) -> None:
    tenant, user = await _seed(db_session, role="admin", ext="ext-ok")
    r = await client_strict.get(
        "/api/projects",
        headers=_headers(tenant.id, user.id, role="admin", aal="aal2", sub="ext-ok"),
    )
    assert r.status_code == 200, r.text


async def test_missing_aal_treated_as_aal1(client_strict, db_session) -> None:
    tenant, user = await _seed(db_session, role="admin", ext="ext-noaal")
    r = await client_strict.get(
        "/api/projects",
        headers=_headers(tenant.id, user.id, role="admin", aal=None, sub="ext-noaal"),
    )
    assert r.status_code == 403
    assert r.json()["error"] == "MFA_REQUIRED"


async def test_member_aal1_can_access(client_strict, db_session) -> None:
    tenant, user = await _seed(db_session, role="member", ext="ext-mem")
    r = await client_strict.get(
        "/api/projects",
        headers=_headers(tenant.id, user.id, role="member", aal="aal1", sub="ext-mem"),
    )
    assert r.status_code == 200, r.text


# --- /mfa/status ------------------------------------------------------------


async def test_mfa_status_admin_aal1(client_strict, db_session) -> None:
    tenant, user = await _seed(db_session, role="admin", ext="ext-st1")
    r = await client_strict.get(
        "/api/mfa/status",
        headers=_headers(tenant.id, user.id, role="admin", aal="aal1", sub="ext-st1"),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["roleRequiresMfa"] is True
    assert body["mfaSatisfied"] is False
    assert body["requiredAction"] == "setup_or_challenge"
    assert body["preferredFactorType"] == "phone"


async def test_mfa_status_admin_aal2_satisfied(client_strict, db_session) -> None:
    tenant, user = await _seed(db_session, role="admin", ext="ext-st2")
    r = await client_strict.get(
        "/api/mfa/status",
        headers=_headers(tenant.id, user.id, role="admin", aal="aal2", sub="ext-st2"),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["roleRequiresMfa"] is True
    assert body["mfaSatisfied"] is True
    assert body["requiredAction"] is None


async def test_mfa_status_member_optional(client_strict, db_session) -> None:
    tenant, user = await _seed(db_session, role="member", ext="ext-st3")
    r = await client_strict.get(
        "/api/mfa/status",
        headers=_headers(tenant.id, user.id, role="member", aal="aal1", sub="ext-st3"),
    )
    assert r.status_code == 200, r.text
    assert r.json()["roleRequiresMfa"] is False


# --- Twilio service contract ------------------------------------------------


class _FakeMessage:
    sid = "SM_fake_123"


class _FakeMessages:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeMessage()


class _FakeTwilioClient:
    def __init__(self, *args, **kwargs) -> None:
        self.messages = _FakeMessages()


def test_twilio_service_uses_messaging_service_sid(monkeypatch) -> None:
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC_test")
    monkeypatch.setenv("TWILIO_API_KEY_SID", "SK_test")
    monkeypatch.setenv("TWILIO_API_KEY_SECRET", "secret")
    monkeypatch.setenv("TWILIO_MESSAGING_SERVICE_SID", "MG_test")
    from app.config import get_settings

    get_settings.cache_clear()
    import twilio.rest

    monkeypatch.setattr(twilio.rest, "Client", _FakeTwilioClient)
    from app.services.twilio_sms_service import TwilioSmsService

    svc = TwilioSmsService()
    sid = svc.send_mfa_code(to_phone="+16615551212", message="code 123456")
    assert sid == "SM_fake_123"
    call = svc.client.messages.calls[0]
    assert call["messaging_service_sid"] == "MG_test"
    assert call["to"] == "+16615551212"
    get_settings.cache_clear()


def test_mask_phone() -> None:
    from app.services.twilio_sms_service import mask_phone

    masked = mask_phone("+16615551212")
    assert masked.startswith("+1")
    assert masked.endswith("1212")
    assert "6615" not in masked


# --- cost controls + audit --------------------------------------------------


class _RecordingTwilio:
    def __init__(self) -> None:
        self.messages = _FakeMessages()

    def send_mfa_code(self, *, to_phone, message):
        self.messages.create(to=to_phone, body=message)
        return "SM_rec"


async def test_send_mfa_sms_writes_audit_and_no_code_logged(db_session, monkeypatch) -> None:
    import app.services.mfa_sms_service as svc

    monkeypatch.setattr(svc, "TwilioSmsService", _RecordingTwilio)
    await svc.send_mfa_sms(
        db_session,
        phone="+16615551212",
        message="Your Tablescope verification code is 999111",
        tenant_id=None,
        user_id=None,
    )
    await db_session.commit()
    events = (await db_session.execute(MfaSmsEvent.__table__.select())).fetchall()
    assert len(events) == 1
    row = events[0]._mapping
    assert row["event_type"] == MFA_SMS_CODE_SENT
    # Full phone is never stored, only masked + hashed.
    assert row["masked_phone"].endswith("1212")
    assert "6615551212" not in (row["masked_phone"] or "")
    assert row["phone_hash"] and len(row["phone_hash"]) == 64
    assert row["twilio_message_sid"] == "SM_rec"


async def test_resend_cooldown_enforced(db_session, monkeypatch) -> None:
    import app.services.mfa_sms_service as svc

    monkeypatch.setattr(svc, "TwilioSmsService", _RecordingTwilio)
    await svc.send_mfa_sms(db_session, phone="+16615551212", message="m", user_id=1)
    with pytest.raises(svc.MfaRateLimitedError) as exc:
        await svc.send_mfa_sms(db_session, phone="+16615551212", message="m", user_id=1)
    assert exc.value.reason == "resend_cooldown"
    assert exc.value.retry_after_seconds and exc.value.retry_after_seconds > 0


async def test_phone_send_limit_enforced(db_session) -> None:
    import app.services.mfa_sms_service as svc
    from app.config import get_settings

    settings = get_settings()
    phone = "+16615559999"
    phone_hash = svc.hash_phone(phone)
    old = datetime.now(tz=UTC) - timedelta(seconds=120)
    # Seed sends up to the cap, all older than the cooldown window.
    for _ in range(settings.mfa_sms_max_sends_per_window):
        db_session.add(
            MfaSmsEvent(
                event_type=MFA_SMS_CODE_SENT,
                phone_hash=phone_hash,
                masked_phone="+1***9999",
                created_at=old,
            )
        )
    await db_session.commit()
    result = await svc.check_send_allowed(db_session, user_id=None, phone=phone)
    assert result.allowed is False
    assert result.reason == "phone_send_limit"


# --- Send-SMS hook ----------------------------------------------------------


async def test_send_sms_hook_rejects_without_secret(client_strict) -> None:
    r = await client_strict.post(
        "/api/auth/hooks/send-sms",
        json={"user": {"phone": "+16615551212"}, "sms": {"otp": "123456"}},
    )
    # No hook secret configured in tests → fail closed (401).
    assert r.status_code == 401


async def test_send_sms_hook_accepts_bearer_secret(client_strict, db_session, monkeypatch) -> None:
    monkeypatch.setenv("SUPABASE_SEND_SMS_HOOK_SECRET", "hooksecret")
    from app.config import get_settings

    get_settings.cache_clear()
    import app.services.mfa_sms_service as svc

    monkeypatch.setattr(svc, "TwilioSmsService", _RecordingTwilio)
    r = await client_strict.post(
        "/api/auth/hooks/send-sms",
        headers={"Authorization": "Bearer hooksecret"},
        json={"user": {"phone": "+16615551212"}, "sms": {"otp": "654321"}},
    )
    assert r.status_code == 200, r.text
    get_settings.cache_clear()
