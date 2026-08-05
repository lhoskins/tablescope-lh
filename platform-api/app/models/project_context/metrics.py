from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from .goals import ProjectGoal, ProjectGoalMetricLink
    from .risks import ProjectRiskMetricLink

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")


class ProjectMetric(TimestampMixin, Base):
    """A project-level business metric with optional source mapping."""

    __tablename__ = "project_metrics"

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
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_definition: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    format: Mapped[str | None] = mapped_column(String(50), nullable=True)
    directionality: Mapped[str] = mapped_column(
        String(20), nullable=False, default="informational"
    )  # higher_is_better, lower_is_better, target_range, informational
    aggregation: Mapped[str] = mapped_column(
        String(50), nullable=False, default="latest"
    )  # sum, average, min, max, count, distinct_count, ratio, latest, custom
    source_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # saved_query, datasource, table_field, expression, manual
    source_query_id: Mapped[int | None] = mapped_column(
        ForeignKey("saved_queries.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_mapping: Mapped[dict | None] = mapped_column(_JSON, nullable=True)
    expression: Mapped[str | None] = mapped_column(Text, nullable=True)
    success_criterion_id: Mapped[int | None] = mapped_column(
        ForeignKey("project_goals.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_match_status: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # searching, candidate_found, validated, matched, no_match, error
    latest_value: Mapped[float | None] = mapped_column(Numeric(19, 6), nullable=True)
    latest_value_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    cadence: Mapped[str | None] = mapped_column(String(50), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    success_criterion: Mapped[ProjectGoal | None] = relationship(
        "ProjectGoal", foreign_keys=[success_criterion_id]
    )
    targets: Mapped[list[ProjectMetricTarget]] = relationship(
        back_populates="metric",
        cascade="all, delete-orphan",
        order_by="ProjectMetricTarget.position",
    )
    goal_links: Mapped[list[ProjectGoalMetricLink]] = relationship(
        back_populates="metric",
        cascade="all, delete-orphan",
    )
    risk_links: Mapped[list[ProjectRiskMetricLink]] = relationship(
        back_populates="metric",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_project_metrics_tenant_project_active", "tenant_id", "project_id", "active"),
        Index("ix_project_metrics_project_position", "project_id", "position"),
    )

    def to_redacted_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "name": self.name,
            "description": self.description,
            "business_definition": self.business_definition,
            "unit": self.unit,
            "format": self.format,
            "directionality": self.directionality,
            "aggregation": self.aggregation,
            "source_type": self.source_type,
            "source_query_id": self.source_query_id,
            "source_mapping": self.source_mapping,
            "expression": self.expression,
            "success_criterion_id": self.success_criterion_id,
            "source_match_status": self.source_match_status,
            "latest_value": float(self.latest_value) if self.latest_value is not None else None,
            "latest_value_at": self.latest_value_at.isoformat() if self.latest_value_at else None,
            "owner_id": self.owner_id,
            "cadence": self.cadence,
            "active": self.active,
            "position": self.position,
            "version": self.version,
        }


class ProjectMetricTarget(TimestampMixin, Base):
    """An effective-dated target for a project metric."""

    __tablename__ = "project_metric_targets"

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
    metric_id: Mapped[int] = mapped_column(
        ForeignKey("project_metrics.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # minimum, maximum, exact, range, increase_by, decrease_by
    target_value: Mapped[float | None] = mapped_column(Numeric(19, 6), nullable=True)
    lower_bound: Mapped[float | None] = mapped_column(Numeric(19, 6), nullable=True)
    upper_bound: Mapped[float | None] = mapped_column(Numeric(19, 6), nullable=True)
    comparison_operator: Mapped[str | None] = mapped_column(
        String(10), nullable=True
    )  # >=, <=, =, between
    warning_threshold: Mapped[float | None] = mapped_column(Numeric(19, 6), nullable=True)
    critical_threshold: Mapped[float | None] = mapped_column(Numeric(19, 6), nullable=True)
    baseline: Mapped[float | None] = mapped_column(Numeric(19, 6), nullable=True)
    effective_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft"
    )  # draft, active, archived
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    metric: Mapped[ProjectMetric] = relationship(back_populates="targets")

    __table_args__ = (
        Index("ix_project_metric_targets_tenant_project", "tenant_id", "project_id"),
        Index("ix_project_metric_targets_metric_active", "metric_id", "active"),
        Index("ix_project_metric_targets_metric_position", "metric_id", "position"),
    )

    def to_redacted_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "metric_id": self.metric_id,
            "target_type": self.target_type,
            "target_value": float(self.target_value) if self.target_value is not None else None,
            "lower_bound": float(self.lower_bound) if self.lower_bound is not None else None,
            "upper_bound": float(self.upper_bound) if self.upper_bound is not None else None,
            "comparison_operator": self.comparison_operator,
            "warning_threshold": float(self.warning_threshold) if self.warning_threshold is not None else None,
            "critical_threshold": float(self.critical_threshold) if self.critical_threshold is not None else None,
            "baseline": float(self.baseline) if self.baseline is not None else None,
            "effective_start": self.effective_start.isoformat() if self.effective_start else None,
            "effective_end": self.effective_end.isoformat() if self.effective_end else None,
            "period": self.period,
            "notes": self.notes,
            "status": self.status,
            "active": self.active,
            "position": self.position,
            "version": self.version,
        }
