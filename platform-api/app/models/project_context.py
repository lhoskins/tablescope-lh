"""Project business context, goals, metrics, targets, and risks.

Structured project intelligence that feeds the AI planner, conversational
analytics, business insight, and repository intelligence while remaining
editable after project creation and fully auditable.
"""

from __future__ import annotations

from datetime import datetime

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

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")


class ProjectBusinessContext(TimestampMixin, Base):
    """Project-level settings and business context.

    Kept separate from :class:`Project` so existing projects stay compatible
    and context can be added lazily.
    """

    __tablename__ = "project_business_contexts"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    business_owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    business_function: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    industry: Mapped[str | None] = mapped_column(String(255), nullable=True)
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    timezone: Mapped[str] = mapped_column(String(100), nullable=False, default="UTC")
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="USD")
    reporting_cadence: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # e.g. weekly, monthly, quarterly, annual
    fiscal_year_start_month: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    ai_context_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    ai_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    interpretation_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        Index("ix_project_business_context_tenant_project", "tenant_id", "project_id"),
    )

    def to_redacted_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "business_owner_id": self.business_owner_id,
            "business_function": self.business_function,
            "industry": self.industry,
            "purpose": self.purpose,
            "timezone": self.timezone,
            "currency": self.currency,
            "reporting_cadence": self.reporting_cadence,
            "fiscal_year_start_month": self.fiscal_year_start_month,
            "ai_context_enabled": self.ai_context_enabled,
            "ai_instructions": self.ai_instructions,
            "interpretation_notes": self.interpretation_notes,
            "version": self.version,
            "updated_by": self.updated_by,
        }


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


class ProjectContextAuditEvent(TimestampMixin, Base):
    """Append-only audit log for project context changes."""

    __tablename__ = "project_context_audit_events"

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
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_type: Mapped[str] = mapped_column(String(50), nullable=False, default="user")
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    previous_value: Mapped[dict | None] = mapped_column(_JSON, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(_JSON, nullable=True)
    version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        Index("ix_project_context_audit_tenant_project", "tenant_id", "project_id"),
        Index("ix_project_context_audit_event_created", "event_type", "created_at"),
    )
