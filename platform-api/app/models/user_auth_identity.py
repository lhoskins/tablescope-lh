"""Identity linking table: external provider subjects to platform users."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class UserAuthIdentity(TimestampMixin, Base):
    __tablename__ = "user_auth_identities"

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "provider_type", "external_subject",
            name="uq_user_auth_identity_subject",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_type: Mapped[str] = mapped_column(String(64), nullable=False)
    external_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    sso_provider_uuid: Mapped[str | None] = mapped_column(String(255), nullable=True)
    directory_connection_id: Mapped[int | None] = mapped_column(
        ForeignKey("ldap_connections.id", ondelete="SET NULL"), nullable=True
    )
    verification_state: Mapped[str] = mapped_column(String(32), nullable=False, default="confirmed")
    linked_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_authenticated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_synchronized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suspended: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    def to_safe_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "provider_type": self.provider_type,
            "external_subject": self.external_subject,
            "verification_state": self.verification_state,
            "sso_provider_uuid": bool(self.sso_provider_uuid),
            "suspended": self.suspended,
            "linked_at": self.linked_at.isoformat() if self.linked_at else None,
            "last_authenticated_at": self.last_authenticated_at.isoformat() if self.last_authenticated_at else None,
            "last_synchronized_at": self.last_synchronized_at.isoformat() if self.last_synchronized_at else None,
        }
