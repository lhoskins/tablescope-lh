"""MFA SMS cost controls + audit.

Wraps :class:`TwilioSmsService` with:
  * resend cooldown (per user / phone),
  * per-user and per-phone send caps within a rolling window,
  * audit rows in ``mfa_sms_events`` for every action,

so SMS cost is bounded and usage is tracked centrally per tenant. Codes and
secrets are never logged or stored; phone numbers are stored masked + hashed.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.mfa_sms_event import (
    MFA_SMS_CODE_SENT,
    MFA_SMS_RATE_LIMITED,
    MfaSmsEvent,
)
from app.services.twilio_sms_service import TwilioSmsService, mask_phone

logger = logging.getLogger(__name__)


def hash_phone(phone: str) -> str:
    """Salted SHA-256 of the E.164 phone, for per-phone rate limiting only."""
    settings = get_settings()
    salt = settings.jwt_secret_key or "tablescope"
    return hashlib.sha256(f"{salt}:{phone.strip()}".encode()).hexdigest()


@dataclass(slots=True)
class RateLimitResult:
    allowed: bool
    reason: str | None = None
    retry_after_seconds: int | None = None


async def record_event(
    session: AsyncSession,
    *,
    event_type: str,
    tenant_id: int | None = None,
    user_id: int | None = None,
    phone: str | None = None,
    twilio_message_sid: str | None = None,
    status: str | None = None,
    failure_reason: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> MfaSmsEvent:
    """Append an audit row. Stores only masked phone + salted hash."""
    event = MfaSmsEvent(
        tenant_id=tenant_id,
        user_id=user_id,
        event_type=event_type,
        masked_phone=mask_phone(phone) if phone else None,
        phone_hash=hash_phone(phone) if phone else None,
        twilio_message_sid=twilio_message_sid,
        status=status,
        failure_reason=failure_reason,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    session.add(event)
    await session.flush()
    return event


async def check_send_allowed(
    session: AsyncSession,
    *,
    user_id: int | None,
    phone: str,
) -> RateLimitResult:
    """Enforce resend cooldown + rolling-window send caps (per user and phone)."""
    settings = get_settings()
    now = datetime.now(tz=UTC)
    phone_hash = hash_phone(phone)

    # Resend cooldown: the most recent send (by user or phone) must be older
    # than the configured cooldown.
    cooldown = settings.mfa_sms_resend_cooldown_seconds
    last_sent = await session.scalar(
        select(func.max(MfaSmsEvent.created_at)).where(
            MfaSmsEvent.event_type == MFA_SMS_CODE_SENT,
            (MfaSmsEvent.phone_hash == phone_hash)
            | (MfaSmsEvent.user_id == user_id if user_id is not None else False),
        )
    )
    if last_sent is not None:
        if last_sent.tzinfo is None:
            last_sent = last_sent.replace(tzinfo=UTC)
        elapsed = (now - last_sent).total_seconds()
        if elapsed < cooldown:
            return RateLimitResult(
                allowed=False,
                reason="resend_cooldown",
                retry_after_seconds=int(cooldown - elapsed) + 1,
            )

    # Rolling-window caps.
    window_start = now - timedelta(seconds=settings.mfa_sms_window_seconds)
    cap = settings.mfa_sms_max_sends_per_window

    phone_sends = await session.scalar(
        select(func.count())
        .select_from(MfaSmsEvent)
        .where(
            MfaSmsEvent.event_type == MFA_SMS_CODE_SENT,
            MfaSmsEvent.phone_hash == phone_hash,
            MfaSmsEvent.created_at >= window_start,
        )
    )
    if (phone_sends or 0) >= cap:
        return RateLimitResult(
            allowed=False,
            reason="phone_send_limit",
            retry_after_seconds=settings.mfa_sms_window_seconds,
        )

    if user_id is not None:
        user_sends = await session.scalar(
            select(func.count())
            .select_from(MfaSmsEvent)
            .where(
                MfaSmsEvent.event_type == MFA_SMS_CODE_SENT,
                MfaSmsEvent.user_id == user_id,
                MfaSmsEvent.created_at >= window_start,
            )
        )
        if (user_sends or 0) >= cap:
            return RateLimitResult(
                allowed=False,
                reason="user_send_limit",
                retry_after_seconds=settings.mfa_sms_window_seconds,
            )

    return RateLimitResult(allowed=True)


async def send_mfa_sms(
    session: AsyncSession,
    *,
    phone: str,
    message: str,
    tenant_id: int | None = None,
    user_id: int | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> MfaSmsEvent:
    """Rate-limit, deliver via Twilio, and audit a single MFA SMS send.

    Raises :class:`MfaRateLimitedError` if a cost control blocks the send.
    """
    decision = await check_send_allowed(session, user_id=user_id, phone=phone)
    if not decision.allowed:
        await record_event(
            session,
            event_type=MFA_SMS_RATE_LIMITED,
            tenant_id=tenant_id,
            user_id=user_id,
            phone=phone,
            status="blocked",
            failure_reason=decision.reason,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        raise MfaRateLimitedError(
            reason=decision.reason or "rate_limited",
            retry_after_seconds=decision.retry_after_seconds,
        )

    service = TwilioSmsService()
    sid = service.send_mfa_code(to_phone=phone, message=message)
    return await record_event(
        session,
        event_type=MFA_SMS_CODE_SENT,
        tenant_id=tenant_id,
        user_id=user_id,
        phone=phone,
        twilio_message_sid=sid,
        status="sent",
        ip_address=ip_address,
        user_agent=user_agent,
    )


class MfaRateLimitedError(RuntimeError):
    def __init__(self, *, reason: str, retry_after_seconds: int | None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retry_after_seconds = retry_after_seconds
