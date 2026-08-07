"""Directory synchronization run tracking."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class DirectorySyncRun(TimestampMixin, Base):
    __tablename__ = "directory_sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("ldap_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trigger: Mapped[str] = mapped_column(String(32), nullable=False)
    configuration_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    phase: Mapped[str | None] = mapped_column(String(64), nullable=True)
    discovered_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    suspended_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    granted_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revoked_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    skipped_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failed_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message_safe: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    initiated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
