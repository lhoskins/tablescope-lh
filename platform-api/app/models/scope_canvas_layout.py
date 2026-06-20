"""Canvas layout for the Scope Relationship Builder.

Stores the on-canvas position of each table card belonging to a scope set so
that reopening the builder restores the exact same layout.  ``table_key`` is a
stable identifier for the card (``query:<id>`` for saved queries); ``query_id``
links it back to the saved query that drives drill-down filtering.
"""

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ScopeCanvasLayout(TimestampMixin, Base):
    __tablename__ = "scope_canvas_layouts"

    id: Mapped[int] = mapped_column(primary_key=True)
    scope_set_id: Mapped[int] = mapped_column(
        ForeignKey("scope_sets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    table_key: Mapped[str] = mapped_column(String(255), nullable=False)
    table_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    query_id: Mapped[int | None] = mapped_column(
        ForeignKey("saved_queries.id", ondelete="CASCADE"),
        nullable=True,
    )
    datasource_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    x_position: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    y_position: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    width: Mapped[float | None] = mapped_column(Float, nullable=True)
    height: Mapped[float | None] = mapped_column(Float, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "scope_set_id": self.scope_set_id,
            "table_key": self.table_key,
            "table_name": self.table_name,
            "query_id": self.query_id,
            "datasource_id": self.datasource_id,
            "x_position": self.x_position,
            "y_position": self.y_position,
            "width": self.width,
            "height": self.height,
        }

    def __repr__(self) -> str:
        return (
            f"ScopeCanvasLayout(id={self.id}, scope_set_id={self.scope_set_id}, "
            f"table_key={self.table_key!r})"
        )
