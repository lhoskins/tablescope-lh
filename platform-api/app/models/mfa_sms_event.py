"""Tenant-level Twilio SMS MFA audit + usage tracking.

Every SMS MFA action (code sent, challenge success/failure, factor changes) is
recorded so usage and cost can be tracked centrally and rate limiting can be
enforced. The full phone number is never stored — only a masked display form
(e.g. ``+1******1212``) and a salted hash for per-phone rate limiting.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class MfaSmsEvent(TimestampMixin, Base):
    __tablename__ = "mfa_sms_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    masked_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    phone_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    twilio_message_sid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)

    __table_args__ = (
        Index("ix_mfa_sms_events_phone_created", "phone_hash", "created_at"),
        Index("ix_mfa_sms_events_user_created", "user_id", "created_at"),
    )


# Recommended event types (free-form ``event_type`` strings).
MFA_SMS_SETUP_STARTED = "mfa_sms_setup_started"
MFA_SMS_CODE_SENT = "mfa_sms_code_sent"
MFA_SMS_CHALLENGE_SUCCESS = "mfa_sms_challenge_success"
MFA_SMS_CHALLENGE_FAILED = "mfa_sms_challenge_failed"
MFA_SMS_FACTOR_REMOVED = "mfa_sms_factor_removed"
MFA_SMS_RATE_LIMITED = "mfa_sms_rate_limited"
