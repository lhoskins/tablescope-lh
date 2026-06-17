"""Intelligence snapshot — the latest persisted AI Intelligence Home run.

One row per user. Each completed run overwrites the previous snapshot so the
Home can hydrate instantly on open while a fresh run streams in the background.
"""

from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

_JSON = JSONB().with_variant(JSON(), "sqlite")


class IntelligenceSnapshot(TimestampMixin, Base):
    __tablename__ = "intelligence_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # One snapshot per user; a new completed run overwrites it.
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    granularity: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    # { projects: [...], results: {projectId: ProjectResult}, synthesis: ... }
    payload: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict)
