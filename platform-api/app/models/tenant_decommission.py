"""Tenant decommission state machine persistence.

A durable control-plane ledger that tracks the irreversible, multi-stage
orchestrated teardown of a tenant. Jobs and events live outside the tenant
cascade so recovery is always possible even after the tenant rows are removed.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

_JSON = JSONB().with_variant(JSON(), "sqlite")


class TenantDecommissionJob(Base, TimestampMixin):
    """Durable orchestration record for one tenant decommission."""

    __tablename__ = "tenant_decommission_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_pk: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    tenant_slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    data_plane_tenant_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )
    requested_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=False
    )
    approved_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    current_step: Mapped[str] = mapped_column(String(50), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    idempotency_key: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True
    )
    confirmation_phrase: Mapped[str] = mapped_column(String(100), nullable=False)

    application_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    infrastructure_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    terraform_workspace: Mapped[str | None] = mapped_column(String(255), nullable=True)
    terraform_state_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    terraform_plan_storage_key: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    terraform_plan_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    terraform_plan_summary: Mapped[dict | None] = mapped_column(_JSON, nullable=True)
    resource_snapshot: Mapped[dict | None] = mapped_column(_JSON, nullable=True)
    dependency_snapshot: Mapped[dict | None] = mapped_column(_JSON, nullable=True)
    verification_results: Mapped[dict | None] = mapped_column(_JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message_safe: Mapped[str | None] = mapped_column(Text, nullable=True)

    requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    frozen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    terraform_applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    aws_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    runtime_cleaned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    data_cleaned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    events: Mapped[list[TenantDecommissionEvent]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="TenantDecommissionEvent.created_at",
    )

    __table_args__ = (
        Index("ix_tenant_decommission_jobs_status", "status"),
        Index("ix_tenant_decommission_jobs_tenant_slug_status", "tenant_slug", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"TenantDecommissionJob(id={self.id!r}, tenant={self.tenant_slug!r}, "
            f"status={self.status!r}, step={self.current_step!r})"
        )


class TenantDecommissionEvent(Base, TimestampMixin):
    """Append-only event stream for a decommission job."""

    __tablename__ = "tenant_decommission_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("tenant_decommission_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(50), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    safe_details: Mapped[dict | None] = mapped_column(_JSON, nullable=True)

    job: Mapped[TenantDecommissionJob] = relationship(back_populates="events")

    def __repr__(self) -> str:
        return (
            f"TenantDecommissionEvent(job_id={self.job_id!r}, step={self.step!r}, "
            f"status={self.status!r})"
        )
