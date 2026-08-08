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
    from .metrics import ProjectMetric
    from .risks import ProjectRisk


class ProjectGoal(TimestampMixin, Base):
    """A project-level business goal."""

    __tablename__ = "project_goals"

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
    priority: Mapped[str] = mapped_column(
        String(20), nullable=False, default="medium"
    )  # low, medium, high, critical
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft"
    )  # draft, active, at_risk, achieved, paused, cancelled
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    target_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    metric_links: Mapped[list[ProjectGoalMetricLink]] = relationship(
        back_populates="goal",
        cascade="all, delete-orphan",
    )
    risk_links: Mapped[list[ProjectGoalRiskLink]] = relationship(
        back_populates="goal",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_project_goals_tenant_project_active", "tenant_id", "project_id", "active"),
        Index("ix_project_goals_project_position", "project_id", "position"),
    )

    @property
    def linked_metric_ids(self) -> list[int]:
        return [link.metric_id for link in self.metric_links]

    @property
    def linked_risk_ids(self) -> list[int]:
        return [link.risk_id for link in self.risk_links]

    def to_redacted_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "priority": self.priority,
            "owner_id": self.owner_id,
            "status": self.status,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "target_date": self.target_date.isoformat() if self.target_date else None,
            "active": self.active,
            "position": self.position,
            "version": self.version,
        }


class ProjectGoalMetricLink(Base):
    """Many-to-many link between goals and metrics."""

    __tablename__ = "project_goal_metric_links"

    goal_id: Mapped[int] = mapped_column(
        ForeignKey("project_goals.id", ondelete="CASCADE"),
        primary_key=True,
    )
    metric_id: Mapped[int] = mapped_column(
        ForeignKey("project_metrics.id", ondelete="CASCADE"),
        primary_key=True,
    )

    goal: Mapped[ProjectGoal] = relationship(back_populates="metric_links")
    metric: Mapped[ProjectMetric] = relationship(back_populates="goal_links")


class ProjectGoalRiskLink(Base):
    """Many-to-many link between goals and risks."""

    __tablename__ = "project_goal_risk_links"

    goal_id: Mapped[int] = mapped_column(
        ForeignKey("project_goals.id", ondelete="CASCADE"),
        primary_key=True,
    )
    risk_id: Mapped[int] = mapped_column(
        ForeignKey("project_risks.id", ondelete="CASCADE"),
        primary_key=True,
    )

    goal: Mapped[ProjectGoal] = relationship(back_populates="risk_links")
    risk: Mapped[ProjectRisk] = relationship(back_populates="goal_links")
