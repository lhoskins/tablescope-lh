"""Verified SMS MFA phone-factor persistence + aal derivation.

A user's verified phone is stored as a single :class:`MfaPhoneFactor` row
(masked + salted hash only — never the full number). A successful Twilio Verify
check refreshes ``verified_until``; ``/auth/exchange`` reads that to decide the
token's ``aal`` claim, so reloads / re-logins inside the window don't re-prompt.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.mfa_policy import AAL2
from app.config import get_settings
from app.models.mfa_phone_factor import MfaPhoneFactor
from app.services.mfa_sms_service import hash_phone
from app.services.twilio_sms_service import mask_phone


async def get_factor(session: AsyncSession, user_id: int) -> MfaPhoneFactor | None:
    """Return the user's phone factor row (active or not), or None."""
    return await session.scalar(
        select(MfaPhoneFactor).where(MfaPhoneFactor.user_id == user_id)
    )


async def get_active_factor(
    session: AsyncSession, user_id: int
) -> MfaPhoneFactor | None:
    """Return the user's verified+active phone factor, or None."""
    factor = await get_factor(session, user_id)
    if factor is not None and factor.active and factor.phone_hash:
        return factor
    return None


def phone_matches_factor(factor: MfaPhoneFactor, phone: str) -> bool:
    """Whether a re-entered phone hashes to the enrolled number."""
    return bool(factor.phone_hash) and factor.phone_hash == hash_phone(phone)


async def upsert_verified_factor(
    session: AsyncSession,
    *,
    tenant_id: int,
    user_id: int,
    phone: str,
) -> MfaPhoneFactor:
    """Record a freshly verified phone and (re)open the aal2 window."""
    now = datetime.now(tz=UTC)
    ttl = timedelta(minutes=get_settings().mfa_session_ttl_minutes)
    factor = await get_factor(session, user_id)
    if factor is None:
        factor = MfaPhoneFactor(tenant_id=tenant_id, user_id=user_id)
        session.add(factor)
    factor.tenant_id = tenant_id
    factor.masked_phone = mask_phone(phone)
    factor.phone_hash = hash_phone(phone)
    factor.active = True
    factor.last_verified_at = now
    factor.verified_until = now + ttl
    await session.flush()
    return factor


async def deactivate_factor(session: AsyncSession, user_id: int) -> bool:
    """Remove a user's phone factor (disable MFA). Returns True if one existed."""
    factor = await get_factor(session, user_id)
    if factor is None:
        return False
    factor.active = False
    factor.verified_until = None
    await session.flush()
    return True


async def mfa_aal_for_user(session: AsyncSession, user_id: int) -> str | None:
    """Return ``"aal2"`` if the user's verification window is still open, else None."""
    factor = await get_active_factor(session, user_id)
    if factor is None or factor.verified_until is None:
        return None
    until = factor.verified_until
    if until.tzinfo is None:
        until = until.replace(tzinfo=UTC)
    if until > datetime.now(tz=UTC):
        return AAL2
    return None
