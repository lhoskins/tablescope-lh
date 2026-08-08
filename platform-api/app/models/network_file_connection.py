"""Tenant-managed SMB/UNC network locations approved for file import.

A connection is the *only* way a user reaches a network share: the entered
path must resolve to an enabled, tenant-owned connection and stay inside its
``approved_root_path``.  The credential is Fernet-encrypted via
``app.services.crypto`` and is never returned by any API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class NetworkFileConnection(TimestampMixin, Base):
    __tablename__ = "network_file_connections"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    protocol: Mapped[str] = mapped_column(
        String(20), nullable=False, default="smb", server_default="smb"
    )
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(
        Integer, nullable=False, default=445, server_default="445"
    )
    share_name: Mapped[str] = mapped_column(String(255), nullable=False)
    #: Share-relative directory prefix every imported path must stay within.
    approved_root_path: Mapped[str] = mapped_column(
        String(1024), nullable=False, default="", server_default=""
    )
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: Fernet token. Never decrypted outside the SMB gateway.
    secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

    require_signing: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    require_encryption: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    last_test_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_test_message_safe: Mapped[str | None] = mapped_column(
        String(512), nullable=True
    )
    last_tested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @property
    def label(self) -> str:
        """Redacted display label: host + share, never a credential."""
        return f"\\\\{self.host}\\{self.share_name}"

    def to_dict(self) -> dict[str, Any]:
        """Editor-safe view. Never includes the username's secret material."""
        return {
            "id": self.id,
            "name": self.name,
            "protocol": self.protocol,
            "label": self.label,
            "host": self.host,
            "port": self.port,
            "share_name": self.share_name,
            "approved_root_path": self.approved_root_path,
            "domain": self.domain,
            "username": self.username,
            "has_secret": bool(self.secret_encrypted),
            "require_signing": self.require_signing,
            "require_encryption": self.require_encryption,
            "enabled": self.enabled,
            "archived": self.archived,
            "last_test_status": self.last_test_status,
            "last_test_message": self.last_test_message_safe,
            "last_tested_at": (
                self.last_tested_at.isoformat() if self.last_tested_at else None
            ),
        }
