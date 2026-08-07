"""Mapping from an external directory group to a TableScope tenant/project role."""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class DirectoryGroupRoleMapping(TimestampMixin, Base):
    __tablename__ = "directory_group_role_mappings"

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "directory_group_guid",
            "target_type",
            "target_project_id",
            "mapped_role",
            name="uq_dir_group_role_mapping",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("ldap_connections.id", ondelete="CASCADE"), nullable=False
    )
    directory_group_guid: Mapped[str] = mapped_column(String(64), nullable=False)
    group_display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    mapped_role: Mapped[str] = mapped_column(String(32), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
