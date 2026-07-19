"""Shared per-project Business Insight result cache.

One row per (tenant, project, granularity) holding the insight cards from the
latest analysis of that project, keyed to the Knowledge Graph version the
analysis was built against. Results are shared across users — project
membership is the visibility boundary (everyone who can open a project sees
the same cards) — so a project's analysis is computed once per data change
instead of once per user. Rows are only ever served through the existing
project access check.
"""

from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

_JSON = JSONB().with_variant(JSON(), "sqlite")


class BusinessInsightResult(TimestampMixin, Base):
    __tablename__ = "business_insight_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    granularity: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    # The active Knowledge Graph version this result was built against; a
    # mismatch with the project's current active version means the result is
    # stale. Nullable: a project may have no lifecycle-managed graph yet, in
    # which case freshness falls back to the TTL alone.
    kg_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_graph_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Fingerprint at build time — observability, and a tiebreaker when the
    # version id is unavailable.
    source_fingerprint: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The insight cards list (the ``insights`` field of a project result).
    payload: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict)
    # User the analysis SQL ran as (project owner for background refreshes).
    built_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "project_id",
            "granularity",
            name="uq_business_insight_result",
        ),
    )
