"""AuditEvent model — immutable log of AI / intelligence actions."""

from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

_JSON = JSONB().with_variant(JSON(), "sqlite")


class AuditEvent(TimestampMixin, Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # e.g. "home_intelligence"
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    # e.g. "risk_sla" | "risk_expiry" | "trend_spend" | "opportunity_supplier"
    prompt_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    scope: Mapped[str | None] = mapped_column(String(100), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    tables_queried: Mapped[list] = mapped_column(_JSON, nullable=False, default=list)
    documents_read: Mapped[list] = mapped_column(_JSON, nullable=False, default=list)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
