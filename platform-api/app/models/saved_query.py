"""Saved query model with project scoping."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class SavedQuery(TimestampMixin, Base):
    __tablename__ = "saved_queries"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    left_datasource: Mapped[str | None] = mapped_column(String(512), nullable=True)
    right_datasource: Mapped[str | None] = mapped_column(String(512), nullable=True)
    join_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    left_column: Mapped[str | None] = mapped_column(String(255), nullable=True)
    right_column: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sql_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_generated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_shared: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    run_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_run_at: Mapped[datetime | None] = mapped_column(nullable=True)
    avg_runtime_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    def __repr__(self) -> str:
        return f"SavedQuery(id={self.id}, project_id={self.project_id}, name={self.name!r})"
