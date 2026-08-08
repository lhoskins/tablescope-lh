"""Durable record of one file acquisition (local upload, URL, or SMB path).

The Data Source Builder acquires bytes three ways but processes them through a
single pipeline.  A ``FileImportJob`` is the tenant-scoped handle for one
acquisition: it survives API restarts, replaces the old process-local upload
session dictionary, and carries only *safe* provenance — never a credential, a
signed query string, or a full sensitive network path.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

_JSON = JSONB().with_variant(JSON(), "sqlite")

ACQUISITION_METHODS = ("local_upload", "url", "network_path")
CONTENT_FAMILIES = ("tabular", "document", "unknown")
IMPORT_STATUSES = (
    "queued",
    "validating",
    "fetching",
    "scanning",
    "profiling",
    "ready",
    "finalizing",
    "completed",
    "failed",
    "cancelled",
    "expired",
)
#: Statuses a job can still be cancelled or finalized from.
ACTIVE_STATUSES = (
    "queued",
    "validating",
    "fetching",
    "scanning",
    "profiling",
    "ready",
)


class FileImportJob(TimestampMixin, Base):
    __tablename__ = "file_import_jobs"
    __table_args__ = (
        Index("ix_file_import_jobs_tenant_status", "tenant_id", "status"),
        Index("ix_file_import_jobs_tenant_requester", "tenant_id", "requested_by"),
    )

    #: UUID string — the canonical ``import_job_id`` used by every route.
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requested_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )

    method: Mapped[str] = mapped_column(String(20), nullable=False)
    content_family: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unknown", server_default="unknown"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="queued", server_default="queued"
    )

    original_file_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    sanitized_file_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    detected_extension: Mapped[str | None] = mapped_column(String(20), nullable=True)
    detected_mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    #: Absolute path of the staged copy inside tenant-scoped quarantine.
    storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)

    source_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: Host + filename only. Never a query string, user-info, or full path.
    source_locator_redacted: Mapped[str | None] = mapped_column(
        String(1024), nullable=True
    )
    network_connection_id: Mapped[int | None] = mapped_column(
        ForeignKey("network_file_connections.id", ondelete="SET NULL"), nullable=True
    )
    remote_etag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    remote_last_modified: Mapped[str | None] = mapped_column(String(255), nullable=True)
    retrieved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: Durable live-source parameters used at query time (URL/UNC path,
    #: network connection id, etc.). Kept separate from the redacted provenance
    #: so Teiid can re-fetch the remote file on every query.
    live_source_params: Mapped[dict[str, Any] | None] = mapped_column(
        _JSON, nullable=True
    )

    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message_safe: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    #: Profile / AI / catalog result reused by finalization. Bounded data only.
    profile_json: Mapped[dict[str, Any] | None] = mapped_column(_JSON, nullable=True)
    #: Populated once the job is finalized so a retry is idempotent.
    result_json: Mapped[dict[str, Any] | None] = mapped_column(_JSON, nullable=True)
    finalized_data_source_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    @property
    def is_terminal(self) -> bool:
        return self.status in ("completed", "failed", "cancelled", "expired")

    def to_dict(self) -> dict[str, Any]:
        """Client-safe view. Deliberately omits storage_key and profile bytes."""
        return {
            "import_job_id": self.id,
            "method": self.method,
            "content_family": self.content_family,
            "status": self.status,
            "file_name": self.sanitized_file_name or self.original_file_name,
            "detected_extension": self.detected_extension,
            "detected_mime_type": self.detected_mime_type,
            "file_size_bytes": self.file_size_bytes,
            "sha256": self.sha256,
            "source_host": self.source_host,
            "source_locator_redacted": self.source_locator_redacted,
            "network_connection_id": self.network_connection_id,
            "retrieved_at": (
                self.retrieved_at.isoformat() if self.retrieved_at else None
            ),
            "error_code": self.error_code,
            "error_message": self.error_message_safe,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "data_source_id": self.finalized_data_source_id,
        }
