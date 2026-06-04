"""Dashboard model — stores widget configuration as JSON per project."""

from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

# JSONB on Postgres, plain JSON on other dialects (e.g. SQLite used in tests).
_JSON = JSONB().with_variant(JSON(), "sqlite")


class Dashboard(TimestampMixin, Base):
    __tablename__ = "dashboards"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft"
    )
    config: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict)

    def __repr__(self) -> str:
        return f"Dashboard(id={self.id}, project_id={self.project_id}, name={self.name!r})"
