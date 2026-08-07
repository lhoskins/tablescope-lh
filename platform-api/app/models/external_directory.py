"""External directory users, groups, and memberships discovered by LDAP sync."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

_JSON = JSONB().with_variant(JSON(), "sqlite")


class ExternalDirectoryUser(TimestampMixin, Base):
    __tablename__ = "external_directory_users"

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "connection_id", "directory_object_guid",
            name="uq_ext_dir_user_tenant_conn_guid",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("ldap_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    directory_object_guid: Mapped[str] = mapped_column(String(64), nullable=False)
    directory_object_sid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    upn: Mapped[str | None] = mapped_column(String(320), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    raw_attributes: Mapped[dict[str, Any] | None] = mapped_column(_JSON, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExternalDirectoryGroup(TimestampMixin, Base):
    __tablename__ = "external_directory_groups"

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "connection_id", "directory_object_guid",
            name="uq_ext_dir_group_tenant_conn_guid",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("ldap_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    directory_object_guid: Mapped[str] = mapped_column(String(64), nullable=False)
    directory_object_sid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_attributes: Mapped[dict[str, Any] | None] = mapped_column(_JSON, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExternalDirectoryMembership(TimestampMixin, Base):
    __tablename__ = "external_directory_memberships"

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "connection_id", "user_id", "group_id",
            name="uq_ext_dir_membership",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("ldap_connections.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("external_directory_users.id", ondelete="CASCADE"), nullable=False
    )
    group_id: Mapped[int] = mapped_column(
        ForeignKey("external_directory_groups.id", ondelete="CASCADE"), nullable=False
    )
    is_nested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
