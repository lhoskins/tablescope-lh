"""Per-user grid preferences for a saved query's result grid.

Stores the user's column ordering and hidden columns for a given saved query so
the MUI X Data Grid restores the same layout on the next visit.  Keyed by
``(user_id, query_id)`` — preferences are personal to each user.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

# JSONB on Postgres, plain JSON on other dialects (e.g. SQLite used in tests).
_JSON = JSONB().with_variant(JSON(), "sqlite")


class GridPreference(TimestampMixin, Base):
    __tablename__ = "grid_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "query_id", name="uq_grid_pref_user_query"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    query_id: Mapped[int] = mapped_column(
        ForeignKey("saved_queries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Ordered list of column field names (left -> right).
    column_order: Mapped[list[str] | None] = mapped_column(_JSON, nullable=True)
    # List of column field names that are hidden.
    hidden_columns: Mapped[list[str] | None] = mapped_column(_JSON, nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "query_id": self.query_id,
            "column_order": self.column_order or [],
            "hidden_columns": self.hidden_columns or [],
        }
