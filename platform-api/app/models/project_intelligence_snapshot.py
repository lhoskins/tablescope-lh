"""Project Insight snapshot — the latest persisted Project Insight run.

One row per (tenant, user, project). Each completed run overwrites the previous
snapshot so the Project Insight page can hydrate instantly on open while a fresh
run rebuilds in the background.
"""

from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

_JSON = JSONB().with_variant(JSON(), "sqlite")


class ProjectIntelligenceSnapshot(TimestampMixin, Base):
    __tablename__ = "project_intelligence_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The serialized ProjectInsightResponse of the last completed run.
    payload: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "user_id",
            "project_id",
            name="uq_project_intelligence_snapshot",
        ),
    )
