"""Project Insight acknowledgement — audit record of a user reviewing an insight.

A "reviewed / acknowledged" marker does NOT mean the user approved or agreed
with the insight; it records that they have seen it, with who and when. One row
per (project, insight_id) — re-acknowledging updates the existing marker.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ProjectInsightAcknowledgement(TimestampMixin, Base):
    __tablename__ = "project_insight_acknowledgements"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Stable identifier of the insight within a project's insight report.
    insight_id: Mapped[str] = mapped_column(String(255), nullable=False)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="reviewed"
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Snapshot of the insight taken at review time so the Reviewed list stays
    # meaningful even after the AI report is regenerated with different items.
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    severity: Mapped[str | None] = mapped_column(String(50), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "project_id", "insight_id", name="uq_project_insight_ack"
        ),
    )

    def __repr__(self) -> str:
        return (
            "ProjectInsightAcknowledgement("
            f"project_id={self.project_id}, insight_id={self.insight_id!r}, "
            f"status={self.status!r})"
        )
