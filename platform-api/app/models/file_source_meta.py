"""Metadata for uploaded-file data sources.

Uploaded files are physically stored on the shared volume and registered as
views inside the owner's VDB by the Teiid import servlet.  This table layers
Tablescope-level metadata on top of those views so we can:

* associate a file data source with a project (item 3),
* soft-archive a file source and later delete it (item 1), and
* remember per-column data-type formatting (item 6).

A row is keyed by ``(tenant_id, owner_id, view_name)`` — the view name is the
stable identifier shared with the query builder.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

# JSONB on Postgres, plain JSON on other dialects (e.g. SQLite used in tests).
_JSON = JSONB().with_variant(JSON(), "sqlite")


class FileSourceMeta(TimestampMixin, Base):
    __tablename__ = "file_source_meta"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "owner_id", "view_name", name="uq_file_source_view"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )

    view_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    vdb_type: Mapped[str] = mapped_column(String(50), nullable=False, default="user")

    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Per-column formatting hints detected on upload, e.g.
    # ``[{"name": "Amount", "type": "currency"}, {"name": "Date_", "type": "date"}]``
    column_types: Mapped[list[dict[str, Any]] | None] = mapped_column(
        _JSON, nullable=True
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "view_name": self.view_name,
            "file_name": self.file_name,
            "project_id": self.project_id,
            "owner_id": self.owner_id,
            "archived": self.archived,
            "archived_at": self.archived_at.isoformat() if self.archived_at else None,
            "column_types": self.column_types or [],
        }
