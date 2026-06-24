"""Knowledge Graph snapshot — the latest persisted full project graph.

One row per (tenant, project, snapshot_key). The Knowledge Graph is expensive to
build (structural Evidence Collector + AI enrichment), so the full merged graph
is cached here and node clicks recenter/filter from the cached nodes/edges.
A manual Refresh rebuilds the snapshot, mirroring AI Home.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

_JSON = JSONB().with_variant(JSON(), "sqlite")

# Single project-level snapshot row key (the full merged graph).
SNAPSHOT_KEY_FULL = "full_project_graph"


class AIProjectGraphSnapshot(Base):
    __tablename__ = "ai_project_graph_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False)
    project_id: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_key: Mapped[str] = mapped_column(String(120), nullable=False)
    payload: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict)
    pipeline_version: Mapped[str] = mapped_column(String(120), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
