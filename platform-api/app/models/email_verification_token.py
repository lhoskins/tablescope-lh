"""Email-ownership verification tokens.

Gates the two-step onboarding flow: a brand-new tenant admin or invited user
must prove they own their email address (by following the ``account_confirmation``
link) *before* the real credential/login email (Supabase invite / set-password
link) is generated and sent. One row per pending verification; consumed once.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class EmailVerificationToken(Base, TimestampMixin):
    __tablename__ = "email_verification_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # SHA-256 hex digest of the raw token -- the raw value is only ever sent in
    # the email link, never persisted.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    # "tenant_admin_invite" (root admin created during tenant onboarding) or
    # "user_invite" (a user added to an existing tenant) -- decides which
    # credential email is sent once verification succeeds.
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
