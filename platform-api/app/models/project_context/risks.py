from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from .goals import ProjectGoalRiskLink
    from .metrics import ProjectMetric


class ProjectRisk(TimestampMixin, Base):
    """A project-level risk register entry."""

    __tablename__ = "project_risks"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    likelihood: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # rare, unlikely, possible, likely, almost_certain
    impact: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # negligible, insignificant, minor, moderate, major, severe, catastrophic
    severity: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # low, medium, high, critical (server-computed)
    rating_matrix_version: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    mitigation: Mapped[str | None] = mapped_column(Text, nullable=True)
    contingency: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open"
    )  # open, monitoring, mitigated, closed, accepted
    review_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    goal_links: Mapped[list[ProjectGoalRiskLink]] = relationship(
        back_populates="risk",
        cascade="all, delete-orphan",
    )
    metric_links: Mapped[list[ProjectRiskMetricLink]] = relationship(
        back_populates="risk",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_project_risks_tenant_project_active", "tenant_id", "project_id", "active"),
        Index("ix_project_risks_project_position", "project_id", "position"),
    )

    @property
    def linked_goal_ids(self) -> list[int]:
        return [link.goal_id for link in self.goal_links]

    @property
    def linked_metric_ids(self) -> list[int]:
        return [link.metric_id for link in self.metric_links]

    def to_redacted_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "likelihood": self.likelihood,
            "impact": self.impact,
            "severity": self.severity,
            "rating_matrix_version": self.rating_matrix_version,
            "owner_id": self.owner_id,
            "mitigation": self.mitigation,
            "contingency": self.contingency,
            "status": self.status,
            "review_date": self.review_date.isoformat() if self.review_date else None,
            "source_reference": self.source_reference,
            "active": self.active,
            "position": self.position,
            "version": self.version,
        }


class ProjectRiskMetricLink(Base):
    """Many-to-many link between risks and metrics."""

    __tablename__ = "project_risk_metric_links"

    risk_id: Mapped[int] = mapped_column(
        ForeignKey("project_risks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    metric_id: Mapped[int] = mapped_column(
        ForeignKey("project_metrics.id", ondelete="CASCADE"),
        primary_key=True,
    )

    risk: Mapped[ProjectRisk] = relationship(back_populates="metric_links")
    metric: Mapped[ProjectMetric] = relationship(back_populates="risk_links")
