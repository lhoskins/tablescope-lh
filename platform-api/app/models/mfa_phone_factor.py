"""Verified SMS MFA phone factor (Twilio Verify).

One row per user records that they have a verified phone for SMS MFA. The full
phone number is never stored — only a masked display form (e.g. ``+1******1212``)
and a salted hash used to (a) confirm a re-entered number matches the enrolled
one at challenge time and (b) key per-phone rate limiting.

``verified_until`` is the moment the current aal2 elevation lapses; after it the
user must complete a fresh SMS challenge. ``/auth/exchange`` derives the token's
``aal`` claim from this record so reloads / re-logins inside the window do not
re-prompt.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class MfaPhoneFactor(TimestampMixin, Base):
    __tablename__ = "mfa_phone_factors"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    masked_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    phone_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    verified_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
