"""Twilio Verify SMS MFA tests.

Covers backend aal2 enforcement for admin roles, the ``/mfa/status`` endpoint,
the Twilio Verify service contract (Verify Service SID, no code/secret logging),
SMS cost controls (resend cooldown + send caps), audit writes, the
start/verify endpoints (OTP send + aal2 token mint), and aal derivation from the
verified-phone record at ``/auth/exchange``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import ClassVar

import pytest

from app.auth.jwt import create_access_token
from app.models.mfa_phone_factor import MfaPhoneFactor
from app.models.mfa_sms_event import (
    MFA_SMS_CHALLENGE_FAILED,
    MFA_SMS_CHALLENGE_SUCCESS,
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


@pytest.fixture(autouse=True)
def _enable_mfa_enforcement(monkeypatch):
    """The enforcement master switch defaults OFF; turn it on for MFA tests."""
    from app.config import get_settings

    monkeypatch.setenv("MFA_ENFORCEMENT_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


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


# --- Fake Twilio Verify -----------------------------------------------------


class _FakeVerify:
    """Drop-in for TwilioVerifyService: records sends, approves a known code."""

    instances: ClassVar[list[_FakeVerify]] = []
    approve_code: ClassVar[str] = "123456"

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.checked: list[tuple[str, str]] = []
        type(self).instances.append(self)

    def start_verification(self, *, to_phone: str) -> str:
        self.sent.append(to_phone)
        return "VE_fake_123"

    def check_verification(self, *, to_phone: str, code: str) -> bool:
        self.checked.append((to_phone, code))
        return code == type(self).approve_code


@pytest.fixture
def fake_verify(monkeypatch):
    import app.services.mfa_sms_service as svc

    _FakeVerify.instances = []
    _FakeVerify.approve_code = "123456"
    monkeypatch.setattr(svc, "TwilioVerifyService", _FakeVerify)
    return _FakeVerify


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


async def test_mfa_status_admin_aal1_no_factor(client_strict, db_session) -> None:
    tenant, user = await _seed(db_session, role="admin", ext="ext-st1")
    r = await client_strict.get(
        "/api/mfa/status",
        headers=_headers(tenant.id, user.id, role="admin", aal="aal1", sub="ext-st1"),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["roleRequiresMfa"] is True
    assert body["mfaSatisfied"] is False
    assert body["hasVerifiedFactor"] is False
    assert body["requiredAction"] == "setup"
    assert body["preferredFactorType"] == "phone"


async def test_mfa_status_admin_aal1_with_factor_is_challenge(
    client_strict, db_session
) -> None:
    tenant, user = await _seed(db_session, role="admin", ext="ext-stf")
    db_session.add(
        MfaPhoneFactor(
            tenant_id=tenant.id,
            user_id=user.id,
            masked_phone="+1******1212",
            phone_hash="x" * 64,
            active=True,
        )
    )
    await db_session.commit()
    r = await client_strict.get(
        "/api/mfa/status",
        headers=_headers(tenant.id, user.id, role="admin", aal="aal1", sub="ext-stf"),
    )
    body = r.json()
    assert body["hasVerifiedFactor"] is True
    assert body["maskedPhone"] == "+1******1212"
    assert body["requiredAction"] == "challenge"


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


async def test_tenant_enforce_2fa_blocks_member_aal1(client_strict, db_session) -> None:
    tenant, user = await _seed(db_session, role="member", ext="ext-t2fa")
    tenant.enforce_2fa = True
    await db_session.commit()
    r = await client_strict.get(
        "/api/projects",
        headers=_headers(tenant.id, user.id, role="member", aal="aal1", sub="ext-t2fa"),
    )
    assert r.status_code == 403
    assert r.json()["error"] == "MFA_REQUIRED"


async def test_tenant_enforce_2fa_status_informs_members_to_setup(client_strict, db_session) -> None:
    tenant, user = await _seed(db_session, role="member", ext="ext-t2fa-st")
    tenant.enforce_2fa = True
    await db_session.commit()
    r = await client_strict.get(
        "/api/mfa/status",
        headers=_headers(tenant.id, user.id, role="member", aal="aal1", sub="ext-t2fa-st"),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["roleRequiresMfa"] is False
    assert body["tenantRequiresMfa"] is True
    assert body["mfaSatisfied"] is False
    assert body["requiredAction"] == "setup"


# --- Twilio Verify service contract -----------------------------------------


class _FakeVerifications:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return type("V", (), {"sid": "VE_x", "status": "pending"})()


class _FakeChecks:
    def __init__(self, status: str) -> None:
        self._status = status
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return type("C", (), {"sid": "VC_x", "status": self._status})()


class _FakeService:
    def __init__(self, check_status: str) -> None:
        self.verifications = _FakeVerifications()
        self.verification_checks = _FakeChecks(check_status)


class _FakeServices:
    def __init__(self, check_status: str) -> None:
        self.requested: list[str] = []
        self._svc = _FakeService(check_status)

    def __call__(self, sid: str):
        self.requested.append(sid)
        return self._svc


class _FakeV2:
    def __init__(self, check_status: str) -> None:
        self.services = _FakeServices(check_status)


class _FakeVerifyNs:
    def __init__(self, check_status: str) -> None:
        self.v2 = _FakeV2(check_status)


class _FakeTwilioClient:
    check_status = "approved"

    def __init__(self, *args, **kwargs) -> None:
        self.verify = _FakeVerifyNs(type(self).check_status)


def _configure_verify(monkeypatch, *, check_status="approved"):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC_test")
    monkeypatch.setenv("TWILIO_API_KEY_SID", "SK_test")
    monkeypatch.setenv("TWILIO_API_KEY_SECRET", "secret")
    monkeypatch.setenv("TWILIO_VERIFY_SERVICE_SID", "VA_test")
    from app.config import get_settings

    get_settings.cache_clear()
    import twilio.rest

    _FakeTwilioClient.check_status = check_status
    monkeypatch.setattr(twilio.rest, "Client", _FakeTwilioClient)


def test_twilio_verify_service_uses_verify_service_sid(monkeypatch) -> None:
    _configure_verify(monkeypatch)
    from app.services.twilio_verify_service import TwilioVerifyService

    svc = TwilioVerifyService()
    sid = svc.start_verification(to_phone="+16615551212")
    assert sid == "VE_x"
    services = svc.client.verify.v2.services
    assert services.requested == ["VA_test"]
    call = services._svc.verifications.calls[0]
    assert call["to"] == "+16615551212"
    assert call["channel"] == "sms"
    from app.config import get_settings

    get_settings.cache_clear()


def test_twilio_verify_check_approved_and_denied(monkeypatch) -> None:
    _configure_verify(monkeypatch, check_status="approved")
    from app.services.twilio_verify_service import TwilioVerifyService

    assert TwilioVerifyService().check_verification(to_phone="+1661", code="1") is True

    _configure_verify(monkeypatch, check_status="pending")
    assert TwilioVerifyService().check_verification(to_phone="+1661", code="1") is False
    from app.config import get_settings

    get_settings.cache_clear()


def test_mask_phone() -> None:
    from app.services.twilio_sms_service import mask_phone

    masked = mask_phone("+16615551212")
    assert masked.startswith("+1")
    assert masked.endswith("1212")
    assert "6615" not in masked


# --- cost controls + audit --------------------------------------------------


async def test_start_verification_writes_audit_and_no_code(
    db_session, fake_verify
) -> None:
    import app.services.mfa_sms_service as svc

    await svc.start_mfa_verification(
        db_session,
        phone="+16615551212",
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
    assert row["twilio_message_sid"] == "VE_fake_123"


async def test_check_verification_audits_success_and_failure(
    db_session, fake_verify
) -> None:
    import app.services.mfa_sms_service as svc

    ok = await svc.check_mfa_verification(
        db_session, phone="+16615551212", code="123456", user_id=1
    )
    bad = await svc.check_mfa_verification(
        db_session, phone="+16615551212", code="000000", user_id=1
    )
    await db_session.commit()
    assert ok is True
    assert bad is False
    types = {
        e._mapping["event_type"]
        for e in (await db_session.execute(MfaSmsEvent.__table__.select())).fetchall()
    }
    assert MFA_SMS_CHALLENGE_SUCCESS in types
    assert MFA_SMS_CHALLENGE_FAILED in types


async def test_resend_cooldown_enforced(db_session, fake_verify) -> None:
    import app.services.mfa_sms_service as svc

    await svc.start_mfa_verification(db_session, phone="+16615551212", user_id=1)
    with pytest.raises(svc.MfaRateLimitedError) as exc:
        await svc.start_mfa_verification(db_session, phone="+16615551212", user_id=1)
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


# --- start / verify endpoints ----------------------------------------------


async def test_phone_start_sends_code(client_strict, db_session, fake_verify) -> None:
    tenant, user = await _seed(db_session, role="admin", ext="ext-start")
    r = await client_strict.post(
        "/api/mfa/phone/start",
        headers=_headers(tenant.id, user.id, role="admin", aal="aal1", sub="ext-start"),
        json={"phone": "+16615551212"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "pending"
    assert body["maskedPhone"].endswith("1212")
    assert fake_verify.instances and fake_verify.instances[-1].sent == ["+16615551212"]


async def test_phone_start_rejects_bad_format(
    client_strict, db_session, fake_verify
) -> None:
    tenant, user = await _seed(db_session, role="admin", ext="ext-bad")
    r = await client_strict.post(
        "/api/mfa/phone/start",
        headers=_headers(tenant.id, user.id, role="admin", aal="aal1", sub="ext-bad"),
        json={"phone": "6615551212"},
    )
    assert r.status_code == 400


async def test_phone_verify_mints_aal2_and_persists_factor(
    client_strict, db_session, fake_verify
) -> None:
    tenant, user = await _seed(db_session, role="admin", ext="ext-verify")
    r = await client_strict.post(
        "/api/mfa/phone/verify",
        headers=_headers(
            tenant.id, user.id, role="admin", aal="aal1", sub="ext-verify"
        ),
        json={"phone": "+16615551212", "code": "123456"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["verified"] is True
    assert body["aal"] == "aal2"
    assert body["access_token"]

    # The minted token actually carries aal2 and unlocks admin routes.
    r2 = await client_strict.get(
        "/api/projects",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert r2.status_code == 200, r2.text

    from app.services.mfa_phone_service import get_factor

    factor = await get_factor(db_session, user.id)
    assert factor is not None
    assert factor.masked_phone.endswith("1212")
    assert "6615551212" not in factor.masked_phone
    assert factor.verified_until is not None


async def test_phone_verify_wrong_code_rejected(
    client_strict, db_session, fake_verify
) -> None:
    tenant, user = await _seed(db_session, role="admin", ext="ext-wrong")
    r = await client_strict.post(
        "/api/mfa/phone/verify",
        headers=_headers(tenant.id, user.id, role="admin", aal="aal1", sub="ext-wrong"),
        json={"phone": "+16615551212", "code": "000000"},
    )
    assert r.status_code == 400


async def test_phone_verify_rejects_mismatched_number(
    client_strict, db_session, fake_verify
) -> None:
    tenant, user = await _seed(db_session, role="admin", ext="ext-mismatch")
    from app.services.mfa_phone_service import hash_phone

    db_session.add(
        MfaPhoneFactor(
            tenant_id=tenant.id,
            user_id=user.id,
            masked_phone="+1******1212",
            phone_hash=hash_phone("+16615551212"),
            active=True,
        )
    )
    await db_session.commit()
    r = await client_strict.post(
        "/api/mfa/phone/start",
        headers=_headers(
            tenant.id, user.id, role="admin", aal="aal1", sub="ext-mismatch"
        ),
        json={"phone": "+19998887777"},
    )
    assert r.status_code == 400


# --- aal derivation from verified factor ------------------------------------


async def test_mfa_aal_for_user_window(db_session) -> None:
    from app.services.mfa_phone_service import mfa_aal_for_user

    tenant, user = await _seed(db_session, role="admin", ext="ext-win")
    # Open window → aal2.
    db_session.add(
        MfaPhoneFactor(
            tenant_id=tenant.id,
            user_id=user.id,
            masked_phone="+1******1212",
            phone_hash="h" * 64,
            active=True,
            verified_until=datetime.now(tz=UTC) + timedelta(hours=1),
        )
    )
    await db_session.commit()
    assert await mfa_aal_for_user(db_session, user.id) == "aal2"


async def test_mfa_aal_for_user_expired_window(db_session) -> None:
    from app.services.mfa_phone_service import mfa_aal_for_user

    tenant, user = await _seed(db_session, role="admin", ext="ext-exp")
    db_session.add(
        MfaPhoneFactor(
            tenant_id=tenant.id,
            user_id=user.id,
            masked_phone="+1******1212",
            phone_hash="h" * 64,
            active=True,
            verified_until=datetime.now(tz=UTC) - timedelta(minutes=1),
        )
    )
    await db_session.commit()
    assert await mfa_aal_for_user(db_session, user.id) is None


async def test_tenant_enforce_2fa_blocks_member_aal1_with_master_switch_off(
    client_strict, db_session, monkeypatch
) -> None:
    """Tenant enforce_2fa must be authoritative even when MFA_ENFORCEMENT_ENABLED=false."""
    from app.config import get_settings

    monkeypatch.setenv("MFA_ENFORCEMENT_ENABLED", "false")
    get_settings.cache_clear()
    tenant, user = await _seed(db_session, role="member", ext="ext-t2fa-master-off")
    tenant.enforce_2fa = True
    await db_session.commit()
    r = await client_strict.get(
        "/api/projects",
        headers=_headers(
            tenant.id, user.id, role="member", aal="aal1", sub="ext-t2fa-master-off"
        ),
    )
    assert r.status_code == 403
    assert r.json()["error"] == "MFA_REQUIRED"


async def test_mfa_status_tenant_requires_ignores_master_switch_off(
    client_strict, db_session, monkeypatch
) -> None:
    from app.config import get_settings

    monkeypatch.setenv("MFA_ENFORCEMENT_ENABLED", "false")
    get_settings.cache_clear()
    tenant, user = await _seed(db_session, role="member", ext="ext-t2fa-st-off")
    tenant.enforce_2fa = True
    await db_session.commit()
    r = await client_strict.get(
        "/api/mfa/status",
        headers=_headers(
            tenant.id, user.id, role="member", aal="aal1", sub="ext-t2fa-st-off"
        ),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["roleRequiresMfa"] is False
    assert body["tenantRequiresMfa"] is True
    assert body["mfaSatisfied"] is False
    assert body["requiredAction"] == "setup"


async def test_remove_phone_blocked_when_tenant_enforces_2fa(
    client_strict, db_session, fake_verify
) -> None:
    tenant, user = await _seed(db_session, role="member", ext="ext-t2fa-del")
    tenant.enforce_2fa = True
    db_session.add(
        MfaPhoneFactor(
            tenant_id=tenant.id,
            user_id=user.id,
            masked_phone="+1******1212",
            phone_hash="x" * 64,
            active=True,
        )
    )
    await db_session.commit()
    r = await client_strict.delete(
        "/api/mfa/phone",
        headers=_headers(
            tenant.id, user.id, role="member", aal="aal2", sub="ext-t2fa-del"
        ),
    )
    assert r.status_code == 400, r.text
    assert "tenant or role policy" in r.json()["detail"]
