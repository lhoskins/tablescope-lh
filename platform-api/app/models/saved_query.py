"""Saved query model with project scoping."""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

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

    def __repr__(self) -> str:
        return f"SavedQuery(id={self.id}, project_id={self.project_id}, name={self.name!r})"
