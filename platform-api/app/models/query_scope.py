"""Query scope (drill-down) model keyed by saved-query id.

A scope maps a *source field* of a saved query to a *target query* + *target
field*.  When a user clicks a scoped cell in the result grid, Tablescope runs
the target query filtered by the clicked value and shows the drill-down result.

Keying on ``query_id`` (the saved-query primary key) keeps scopes stable even
when a query is renamed or its datasource display name changes.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class QueryScope(TimestampMixin, Base):
    __tablename__ = "query_scopes"

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
    # Source saved query + the field a scope hangs off of.
    query_id: Mapped[int] = mapped_column(
        ForeignKey("saved_queries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_field: Mapped[str] = mapped_column(String(255), nullable=False)
    # Target saved query + the field filtered by the clicked value.
    target_query_id: Mapped[int] = mapped_column(
        ForeignKey("saved_queries.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_field: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "query_id": self.query_id,
            "source_field": self.source_field,
            "target_query_id": self.target_query_id,
            "target_field": self.target_field,
        }

    def __repr__(self) -> str:
        return (
            f"QueryScope(id={self.id}, query_id={self.query_id}, "
            f"source_field={self.source_field!r} -> "
            f"target_query_id={self.target_query_id}, target_field={self.target_field!r})"
        )
