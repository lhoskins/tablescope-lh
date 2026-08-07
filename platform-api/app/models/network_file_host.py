"""Tenant-managed SMB host allowlist for Data Source Builder security.

A host entry is a friendly, administrator-approved server that network file
imports are allowed to reach. It is separate from a :class:`NetworkFileConnection`
(which adds share/credential detail) so an admin can approve a host before any
connection or credential is created.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class NetworkFileHost(TimestampMixin, Base):
    __tablename__ = "network_file_hosts"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    #: Friendly display name (e.g. "Customer repository VM").
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    #: Hostname or IP address used in UNC/SMB locators.
    host: Mapped[str] = mapped_column(String(255), nullable=False)

    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "name": self.name,
            "host": self.host,
            "enabled": self.enabled,
            "archived": self.archived,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
