"""Query scope (drill-down) model keyed by saved-query id.

A scope maps a *source field* of a saved query to a *target query* + *target
field*.  When a user clicks a scoped cell in the result grid, Tablescope runs
the target query filtered by the clicked value and shows the drill-down result.

Keying on ``query_id`` (the saved-query primary key) keeps scopes stable even
when a query is renamed or its datasource display name changes.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String
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
    # Parent scope set this mapping belongs to (nullable for legacy rows).
    scope_set_id: Mapped[int | None] = mapped_column(
        ForeignKey("scope_sets.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # Source saved query + the field a scope hangs off of.
    query_id: Mapped[int] = mapped_column(
        ForeignKey("saved_queries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_field: Mapped[str] = mapped_column(String(255), nullable=False)
    # Display name of the source table/query card on the builder canvas.
    source_table: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Target saved query + the field filtered by the clicked value.
    target_query_id: Mapped[int] = mapped_column(
        ForeignKey("saved_queries.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_field: Mapped[str] = mapped_column(String(255), nullable=False)
    target_table: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # "source_to_target" (default) | "target_to_source"
    direction: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="source_to_target",
        server_default="source_to_target",
    )
    # Lines sharing a match_group_id form a multi-field relationship.
    match_group_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # "all" — every field in the group must match; "any" — any field matches.
    match_mode: Mapped[str] = mapped_column(
        String(8), nullable=False, default="all", server_default="all"
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_by_ai: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
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
            "scope_set_id": self.scope_set_id,
            "query_id": self.query_id,
            "source_field": self.source_field,
            "source_table": self.source_table,
            "target_query_id": self.target_query_id,
            "target_field": self.target_field,
            "target_table": self.target_table,
            "direction": self.direction,
            "match_group_id": self.match_group_id,
            "match_mode": self.match_mode,
            "enabled": self.enabled,
            "confidence_score": self.confidence_score,
            "created_by_ai": self.created_by_ai,
        }

    def __repr__(self) -> str:
        return (
            f"QueryScope(id={self.id}, query_id={self.query_id}, "
            f"source_field={self.source_field!r} -> "
            f"target_query_id={self.target_query_id}, target_field={self.target_field!r})"
        )
