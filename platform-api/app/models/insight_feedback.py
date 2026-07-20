"""Human feedback on individual AI-generated insights.

One active feedback record per (tenant_id, user_id, insight_id). The user's own
feedback is surfaced on cards they see; it is never aggregated or shown to other
users, and it is never used to automatically retrain the model.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models.base import Base, TimestampMixin

_JSON = JSONB().with_variant(JSON(), "sqlite")


class InsightFeedback(TimestampMixin, Base):
    __tablename__ = "insight_feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    insight_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    snapshot_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    insight_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sentiment: Mapped[str] = mapped_column(String(20), nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(_JSON, nullable=False, default=list)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    insight_fingerprint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    card_snapshot: Mapped[dict | None] = mapped_column(_JSON, nullable=True)
    explanation_snapshot: Mapped[dict | None] = mapped_column(_JSON, nullable=True)
    model_metadata: Mapped[dict | None] = mapped_column(_JSON, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active"
    )
    review_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    reviewer_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reviewer_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "user_id", "insight_id",
            name="uix_insight_feedback_tenant_user_insight",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"InsightFeedback(id={self.id}, tenant_id={self.tenant_id}, "
            f"user_id={self.user_id}, insight_id={self.insight_id!r}, "
            f"sentiment={self.sentiment!r}, status={self.status!r}, "
            f"review_status={self.review_status!r})"
        )
