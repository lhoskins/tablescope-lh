"""DB Admin data source assignments (issue 5).

A ``DatabaseDataSourceAssignment`` grants a user access to an
already-configured :class:`DatabaseDataSource` without exposing the underlying
credentials.  An Admin or DB Admin creates the assignment and chooses the
friendly name the user sees; the assigned source then appears in the user's
Data Source Builder under "Connected Databases".

The connector/credential is inherited from the assigned datasource, so the
user can build and run queries against it but can never read or edit the raw
connection secrets.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class DatabaseDataSourceAssignment(TimestampMixin, Base):
    __tablename__ = "database_data_source_assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    database_data_source_id: Mapped[int] = mapped_column(
        ForeignKey("database_data_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Stored redundantly when the datasource was created from a saved
    # connection profile, so the builder can list tables without re-resolving
    # the source.  NULL for inline-credential datasources.
    database_connection_id: Mapped[int | None] = mapped_column(
        ForeignKey("database_connections.id", ondelete="SET NULL"),
        nullable=True,
    )
    assigned_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    friendly_name: Mapped[str] = mapped_column(String(255), nullable=False)
    read_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    assigned_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "database_data_source_id",
            "assigned_user_id",
            name="uq_dds_assignment_tenant_source_user",
        ),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "database_data_source_id": self.database_data_source_id,
            "database_connection_id": self.database_connection_id,
            "assigned_user_id": self.assigned_user_id,
            "friendly_name": self.friendly_name,
            "read_only": self.read_only,
            "is_active": self.is_active,
            "assigned_by": self.assigned_by,
            "created_at": self.created_at.isoformat()
            if self.created_at
            else None,
            "updated_at": self.updated_at.isoformat()
            if self.updated_at
            else None,
        }

    def __repr__(self) -> str:
        return (
            f"DatabaseDataSourceAssignment(id={self.id}, "
            f"source={self.database_data_source_id}, "
            f"user={self.assigned_user_id}, active={self.is_active})"
        )
