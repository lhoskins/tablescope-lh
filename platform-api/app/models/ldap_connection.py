"""LDAP directory connection, modeled on network_file_connections."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class LdapConnection(TimestampMixin, Base):
    __tablename__ = "ldap_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    protocol: Mapped[str] = mapped_column(String(20), nullable=False, default="ldaps")
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False, default=636)
    base_dn: Mapped[str] = mapped_column(String(1024), nullable=False)
    user_search_base: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    user_filter: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    group_search_base: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    group_filter: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    bind_dn: Mapped[str | None] = mapped_column(String(512), nullable=True)
    bind_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    ca_certificate: Mapped[str | None] = mapped_column(Text, nullable=True)
    use_starttls: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    require_cert_validation: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    connect_timeout: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    page_size: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    nested_group_resolution: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    max_nested_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    sync_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    disabled_user_handling: Mapped[str] = mapped_column(String(32), nullable=False, default="suspend")
    removed_group_handling: Mapped[str] = mapped_column(String(32), nullable=False, default="revoke")

    tenant_data_plane_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenant_data_planes.id", ondelete="SET NULL"), nullable=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_test_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_test_message_safe: Mapped[str | None] = mapped_column(String(512), nullable=True)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def has_bind_secret(self) -> bool:
        return bool(self.bind_secret_encrypted)

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "name": self.name,
            "protocol": self.protocol,
            "host": self.host,
            "port": self.port,
            "base_dn": self.base_dn,
            "user_search_base": self.user_search_base,
            "user_filter": self.user_filter,
            "group_search_base": self.group_search_base,
            "group_filter": self.group_filter,
            "bind_dn": self.bind_dn,
            "has_bind_secret": self.has_bind_secret,
            "ca_certificate": bool(self.ca_certificate),
            "use_starttls": self.use_starttls,
            "require_cert_validation": self.require_cert_validation,
            "connect_timeout": self.connect_timeout,
            "page_size": self.page_size,
            "nested_group_resolution": self.nested_group_resolution,
            "max_nested_depth": self.max_nested_depth,
            "sync_interval_minutes": self.sync_interval_minutes,
            "disabled_user_handling": self.disabled_user_handling,
            "removed_group_handling": self.removed_group_handling,
            "tenant_data_plane_id": self.tenant_data_plane_id,
            "enabled": self.enabled,
            "archived": self.archived,
            "last_test_status": self.last_test_status,
            "last_test_message_safe": self.last_test_message_safe,
            "last_tested_at": self.last_tested_at.isoformat() if self.last_tested_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
