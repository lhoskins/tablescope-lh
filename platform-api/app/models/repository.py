"""Enterprise repository intelligence persistence models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON as SqlalchemyJSON
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

_JSON = JSONB().with_variant(SqlalchemyJSON(), "sqlite")


class RepositoryConnection(TimestampMixin, Base):
    """A configured repository connector (e.g. UNC/SMB)."""

    __tablename__ = "repository_connections"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    connector_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="active"
    )  # active | disabled | error
    config_json: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict)
    credential_id: Mapped[int | None] = mapped_column(
        ForeignKey("connector_credentials.id", ondelete="SET NULL"), nullable=True
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    scan_schedule: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_scan_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_successful_scan_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        Index("ix_repository_connections_tenant_enabled", "tenant_id", "is_enabled"),
    )

    def to_redacted_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "name": self.name,
            "description": self.description,
            "connector_type": self.connector_type,
            "status": self.status,
            "config": self.config_json,
            "has_credential": self.credential_id is not None,
            "project_id": self.project_id,
            "is_enabled": self.is_enabled,
            "scan_schedule": self.scan_schedule,
            "last_scan_id": self.last_scan_id,
            "last_successful_scan_at": (
                self.last_successful_scan_at.isoformat()
                if self.last_successful_scan_at
                else None
            ),
            "version": self.version,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class RepositoryScan(TimestampMixin, Base):
    """A single scan run for a repository connection."""

    __tablename__ = "repository_scans"

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("repository_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trigger_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # manual | scheduled
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="queued"
    )  # queued | running | succeeded | partial | failed | cancelled
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checkpoint_json: Mapped[dict | None] = mapped_column(_JSON, nullable=True)
    files_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    directories_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bytes_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    added_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    changed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deleted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    retry_attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    project_context_summary: Mapped[dict | None] = mapped_column(_JSON, nullable=True)
    project_context_version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    connection: Mapped[RepositoryConnection] = relationship(
        "RepositoryConnection",
        foreign_keys=[connection_id],
    )

    __table_args__ = (
        Index("ix_repository_scans_status_heartbeat", "status", "heartbeat_at"),
    )

    def to_summary_dict(self) -> dict:
        return {
            "id": self.id,
            "connection_id": self.connection_id,
            "tenant_id": self.tenant_id,
            "trigger_type": self.trigger_type,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "heartbeat_at": self.heartbeat_at.isoformat() if self.heartbeat_at else None,
            "files_seen": self.files_seen,
            "directories_seen": self.directories_seen,
            "bytes_seen": self.bytes_seen,
            "added_count": self.added_count,
            "changed_count": self.changed_count,
            "deleted_count": self.deleted_count,
            "skipped_count": self.skipped_count,
            "error_count": self.error_count,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "worker_id": self.worker_id,
            "retry_attempt": self.retry_attempt,
            "project_context_summary": self.project_context_summary,
            "project_context_version": self.project_context_version,
        }


class RepositoryItem(TimestampMixin, Base):
    """A file or directory discovered by a repository scan."""

    __tablename__ = "repository_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("repository_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    relative_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    name: Mapped[str] = mapped_column(String(1024), nullable=False)
    parent_path: Mapped[str] = mapped_column(String(2048), nullable=False, default="/")
    item_type: Mapped[str] = mapped_column(String(50), nullable=False)
    extension: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_modified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    etag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen_scan_id: Mapped[int | None] = mapped_column(
        ForeignKey("repository_scans.id"), nullable=True
    )
    last_seen_scan_id: Mapped[int | None] = mapped_column(
        ForeignKey("repository_scans.id"), nullable=True
    )
    last_changed_scan_id: Mapped[int | None] = mapped_column(
        ForeignKey("repository_scans.id"), nullable=True
    )
    extraction_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending"
    )  # pending | queued | completed | failed | skipped | governance_blocked

    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_repository_item_connection_external"),
        Index("ix_repository_items_path", "connection_id", "relative_path"),
        Index("ix_repository_items_last_seen", "connection_id", "last_seen_scan_id"),
        Index("ix_repository_items_extraction", "connection_id", "extraction_status"),
        Index("ix_repository_items_deleted", "connection_id", "is_deleted"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "connection_id": self.connection_id,
            "external_id": self.external_id,
            "relative_path": self.relative_path,
            "name": self.name,
            "parent_path": self.parent_path,
            "item_type": self.item_type,
            "extension": self.extension,
            "mime_type": self.mime_type,
            "size": self.size,
            "source_created_at": (
                self.source_created_at.isoformat() if self.source_created_at else None
            ),
            "source_modified_at": (
                self.source_modified_at.isoformat() if self.source_modified_at else None
            ),
            "etag": self.etag,
            "content_hash": self.content_hash,
            "metadata": self.metadata_json,
            "is_deleted": self.is_deleted,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "first_seen_scan_id": self.first_seen_scan_id,
            "last_seen_scan_id": self.last_seen_scan_id,
            "last_changed_scan_id": self.last_changed_scan_id,
            "extraction_status": self.extraction_status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class RepositoryProfile(TimestampMixin, Base):
    """Aggregated repository profile from a scan."""

    __tablename__ = "repository_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("repository_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scan_id: Mapped[int | None] = mapped_column(
        ForeignKey("repository_scans.id", ondelete="SET NULL"), nullable=True, index=True
    )
    profile_json: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict)
    project_context_summary: Mapped[dict | None] = mapped_column(_JSON, nullable=True)
    project_context_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        Index("ix_repository_profiles_current", "connection_id", "is_current"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "connection_id": self.connection_id,
            "scan_id": self.scan_id,
            "profile": self.profile_json,
            "project_context_summary": self.project_context_summary,
            "project_context_version": self.project_context_version,
            "is_current": self.is_current,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
