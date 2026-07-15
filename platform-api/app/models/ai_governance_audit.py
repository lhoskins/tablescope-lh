"""Append-only audit log for AI governance decisions and policy changes."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models.base import Base, TimestampMixin

_JSON = JSONB().with_variant(JSON(), "sqlite")


class AIGovernanceAuditEvent(TimestampMixin, Base):
    """A single governance-relevant event.

    Includes policy changes, method evaluations, fallback selections, and
    blocked requests.  Rows are never updated or deleted through the application.
    """

    __tablename__ = "ai_governance_audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="user"
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    method_key: Mapped[str | None] = mapped_column(
        String(150), nullable=True, index=True
    )
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    conversation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    turn_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    insight_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    policy_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    previous_value: Mapped[dict | None] = mapped_column(_JSON, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(_JSON, nullable=True)
    decision: Mapped[str | None] = mapped_column(
        String(50), nullable=True, index=True
    )
    reason_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    details: Mapped[dict | None] = mapped_column(_JSON, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        Index(
            "ix_ai_governance_audit_tenant_created",
            "tenant_id",
            "created_at",
        ),
    )
