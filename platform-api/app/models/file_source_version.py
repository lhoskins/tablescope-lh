"""Immutable version records for uploaded-file data sources.

Every drag-to-update / ``Update data source`` run stages the incoming file as a
new row here before anything touches the live view. The active version points
at the file currently published to Teiid; superseded versions keep their
archived copy on disk so an authorized user can roll back to them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

_JSON = JSONB().with_variant(JSON(), "sqlite")

# Lifecycle of a version row.
STATUS_STAGED = "staged"
STATUS_ACTIVE = "active"
STATUS_ARCHIVED = "archived"
STATUS_FAILED = "failed"
STATUS_ROLLED_BACK = "rolled_back"


class FileSourceVersion(TimestampMixin, Base):
    __tablename__ = "file_source_version"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_source_id: Mapped[int] = mapped_column(
        ForeignKey("file_source_meta.id", ondelete="CASCADE"), nullable=False, index=True
    )
    uploader_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=STATUS_STAGED)
    update_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="replace")

    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    stored_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    column_types: Mapped[list[dict[str, Any]] | None] = mapped_column(_JSON, nullable=True)
    # Preflight result: added/removed/type-changed columns, dependencies, blockers.
    compatibility: Mapped[dict[str, Any] | None] = mapped_column(_JSON, nullable=True)

    replaced_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("file_source_version.id", ondelete="SET NULL"), nullable=True
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "versionNumber": self.version_number,
            "status": self.status,
            "updateMode": self.update_mode,
            "originalFilename": self.original_filename,
            "checksum": self.checksum,
            "sizeBytes": self.size_bytes,
            "rowCount": self.row_count,
            "columnTypes": self.column_types or [],
            "compatibility": self.compatibility or {},
            "uploaderId": self.uploader_id,
            "replacedVersionId": self.replaced_version_id,
            "activatedAt": self.activated_at.isoformat() if self.activated_at else None,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "errorMessage": self.error_message,
        }
