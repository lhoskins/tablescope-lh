"""Directory-derived tenant/project grants with provenance."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class DirectoryDerivedGrant(TimestampMixin, Base):
    __tablename__ = "directory_derived_grants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mapping_id: Mapped[int] = mapped_column(
        ForeignKey("directory_group_role_mappings.id", ondelete="CASCADE"), nullable=False
    )
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("ldap_connections.id", ondelete="CASCADE"), nullable=False
    )
    directory_group_guid: Mapped[str] = mapped_column(String(64), nullable=False)
    sync_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("directory_sync_runs.id", ondelete="SET NULL"), nullable=True
    )
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
