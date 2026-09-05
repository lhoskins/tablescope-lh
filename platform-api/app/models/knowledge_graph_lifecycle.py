"""Knowledge graph lifecycle, versioning, builds, and health checks."""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")


class KnowledgeGraph(Base, TimestampMixin):
    """Project-level knowledge graph state and active version pointer."""

    __tablename__ = "knowledge_graphs"

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
    active_version_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        index=True,
    )
    last_healthy_version_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        index=True,
    )
    lifecycle_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="missing"
    )  # requested | queued | building | validating | ready | active | degraded | stale | failed | disabled | rebuilding | superseded
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    current_source_fingerprint: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    last_successful_build_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_health_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("ix_knowledge_graphs_tenant_project", "tenant_id", "project_id"),
    )


class KnowledgeGraphVersion(Base, TimestampMixin):
    """A candidate or historical knowledge graph snapshot pointer."""

    __tablename__ = "knowledge_graph_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    graph_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_graphs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
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
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    build_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="candidate"
    )  # candidate | validating | ready | active | failed | superseded
    build_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="full"
    )  # full | incremental | repair | validation_only
    source_fingerprint: Mapped[str | None] = mapped_column(Text, nullable=True)
    node_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    edge_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    disconnected_component_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    validation_summary: Mapped[dict | None] = mapped_column(_JSON, nullable=True)
    storage_reference: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # snapshot_key in ai_project_graph_snapshots
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index(
            "ix_knowledge_graph_versions_project_version",
            "project_id",
            "version_number",
            unique=True,
        ),
        Index(
            "ix_knowledge_graph_versions_status",
            "tenant_id",
            "project_id",
            "status",
        ),
    )


class KnowledgeGraphBuild(Base, TimestampMixin):
    """A single knowledge graph build/run tracked by the lifecycle manager."""

    __tablename__ = "knowledge_graph_builds"

    id: Mapped[int] = mapped_column(primary_key=True)
    graph_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_graphs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
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
    trigger_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="manual"
    )  # manual | scheduled | change_event | retry
    build_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="full"
    )  # full | incremental | repair | validation_only
    requested_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="queued"
    )  # queued | building | validating | ready | failed | cancelled | succeeded
    queued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_checkpoint: Mapped[dict | None] = mapped_column(_JSON, nullable=True)
    affected_entity_summary: Mapped[dict | None] = mapped_column(_JSON, nullable=True)
    # KG-48: per-stage duration breakdown (ms) plus source counts, keyed by
    # stage name -- e.g. {"durations_ms": {"queued": 40, "fingerprinting":
    # 210, "loading_sources": 1500, "ai_enrichment": 8200, "validating": 90,
    # "activating": 15}, "source_counts": {...}} -- so an operator can see
    # which stage was slow or where a build failed for any build_id without
    # reading raw logs.
    stage_metrics: Mapped[dict | None] = mapped_column(_JSON, nullable=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stage: Mapped[str] = mapped_column(
        String(100), nullable=False, default="initializing"
    )
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    safe_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    worker_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    candidate_version_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        index=True,
    )

    __table_args__ = (
        Index(
            "ix_knowledge_graph_builds_project_status",
            "project_id",
            "status",
        ),
        Index(
            "ix_knowledge_graph_builds_heartbeat",
            "status",
            "heartbeat_at",
        ),
    )



class KnowledgeGraphHealthCheck(Base, TimestampMixin):
    """Health check result for a knowledge graph version."""

    __tablename__ = "knowledge_graph_health_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    graph_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_graphs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    version_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_graph_versions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
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
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="unknown"
    )  # healthy | warning | degraded | stale | unhealthy | unavailable
    check_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="on_demand"
    )  # on_demand | post_build | scheduled | pre_executive_insight
    structural_checks: Mapped[dict | None] = mapped_column(_JSON, nullable=True)
    source_alignment: Mapped[dict | None] = mapped_column(_JSON, nullable=True)
    dependency_checks: Mapped[dict | None] = mapped_column(_JSON, nullable=True)
    node_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    edge_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    orphan_ratio: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    disconnected_components: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    warnings: Mapped[list | None] = mapped_column(_JSON, nullable=True)
    errors: Mapped[list | None] = mapped_column(_JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index(
            "ix_knowledge_graph_health_checks_project",
            "tenant_id",
            "project_id",
            "completed_at",
        ),
    )


