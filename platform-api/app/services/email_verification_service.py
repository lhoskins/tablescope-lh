"""Two-step "verify email before sending credentials" onboarding gate.

Both the tenant-onboarding root-admin path and the tenant-user invite path
create a local :class:`User` first, then call :func:`send_verification_email`
instead of generating a Supabase invite / password-setup link right away.
Only after the recipient follows that link (``POST /api/auth/verify-email``,
which calls :func:`consume_verification_token`) does the caller proceed to
create the Supabase identity and send the real credential email -- so a typo'd
or unowned address never receives login information.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email_verification_token import EmailVerificationToken
from app.models.user import User

TENANT_ADMIN_INVITE = "tenant_admin_invite"
USER_INVITE = "user_invite"

_TOKEN_TTL_HOURS = 24


class VerificationTokenError(ValueError):
    """Raised when a verification token is unknown, expired, or already used."""


@dataclass(slots=True)
class VerificationResult:
    user: User
    purpose: str
    already_verified: bool


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


async def create_verification_token(
    session: AsyncSession,
    *,
    tenant_id: int,
    user_id: int,
    purpose: str,
) -> str:
    """Create (or replace) a pending verification token for this user+purpose.

    Returns the raw token -- callers embed it in the confirmation link. Only
    the SHA-256 hash is persisted.
    """
    # Invalidate any earlier pending token for the same purpose so only the
    # most recently sent email link is valid (avoids stale-link confusion on
    # a resend).
    existing = await session.scalars(
        select(EmailVerificationToken).where(
            EmailVerificationToken.tenant_id == tenant_id,
            EmailVerificationToken.user_id == user_id,
            EmailVerificationToken.purpose == purpose,
            EmailVerificationToken.consumed_at.is_(None),
        )
    )
    now = datetime.now(UTC)
    for row in existing:
        row.consumed_at = now

    raw_token = secrets.token_urlsafe(32)
    session.add(
        EmailVerificationToken(
            tenant_id=tenant_id,
            user_id=user_id,
            token_hash=_hash_token(raw_token),
            purpose=purpose,
            expires_at=now + timedelta(hours=_TOKEN_TTL_HOURS),
        )
    )
    await session.flush()
    return raw_token


async def consume_verification_token(
    session: AsyncSession, raw_token: str
) -> VerificationResult:
    """Validate and consume a verification token, marking the user verified.

    Idempotent: a token for a user who is already verified (e.g. the link was
    clicked twice) succeeds without error and reports ``already_verified``.
    Raises :class:`VerificationTokenError` for an unknown, expired, or
    already-consumed-by-a-different-click token.
    """
    row = await session.scalar(
        select(EmailVerificationToken).where(
            EmailVerificationToken.token_hash == _hash_token(raw_token)
        )
    )
    if row is None:
        raise VerificationTokenError("Invalid or expired verification link")

    user = await session.get(User, row.user_id)
    if user is None or user.tenant_id != row.tenant_id:
        raise VerificationTokenError("Invalid or expired verification link")

    if row.consumed_at is not None:
        if user.email_verified:
            return VerificationResult(
                user=user, purpose=row.purpose, already_verified=True
            )
        raise VerificationTokenError("Invalid or expired verification link")

    now = datetime.now(UTC)
    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at < now:
        raise VerificationTokenError("This verification link has expired")

    row.consumed_at = now
    already_verified = user.email_verified
    user.email_verified = True
    user.email_verified_at = user.email_verified_at or now
    await session.flush()
    return VerificationResult(
        user=user, purpose=row.purpose, already_verified=already_verified
    )
