"""Database-backed data source models.

A ``DatabaseDataSource`` represents one external database table that has been
registered as an independent Tablescope data source.  It mirrors the lifecycle
of an uploaded file (create -> inspect -> register in Teiid -> query -> join)
but is backed by a JDBC connection instead of a file on disk.

The schema is intentionally split so a future release can refactor the stored
connection fields into a shared/admin-managed connection profile without
rewriting the query builder: the only thing the query builder depends on is the
Teiid view name (``teiid_view_name``).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class DatabaseDataSource(TimestampMixin, Base):
    __tablename__ = "database_data_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="database_table"
    )
    # For SaaS-backed sources (source_type="saas_object") this records the
    # connector that produced the staging table (e.g. "hubspot",
    # "salesforce").  NULL for plain database tables.  The badge/UI use it to
    # show the source's origin even though the staging table is just Postgres.
    connector_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    db_type: Mapped[str] = mapped_column(String(50), nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    database_name: Mapped[str] = mapped_column(String(255), nullable=False)
    schema_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    table_name: Mapped[str] = mapped_column(String(255), nullable=False)

    username: Mapped[str] = mapped_column(String(255), nullable=False)
    # Fernet-encrypted password.  Never returned to the UI.
    password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    ssl_mode: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Teiid registration metadata
    teiid_model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    teiid_table_name: Mapped[str] = mapped_column(String(255), nullable=False)
    teiid_view_name: Mapped[str] = mapped_column(String(255), nullable=False)
    teiid_jndi_name: Mapped[str] = mapped_column(String(255), nullable=False)

    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")
    # Soft-archive: archived sources are hidden from the active datasource list
    # but kept so they can be deleted once no active query depends on them.
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_test_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_test_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_tested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    columns: Mapped[list[DataSourceColumn]] = relationship(
        back_populates="data_source",
        cascade="all, delete-orphan",
        order_by="DataSourceColumn.ordinal_position",
    )

    def to_dict(self) -> dict:
        """Serialize for the UI.  Never includes the password."""
        return {
            "id": self.id,
            "project_id": self.project_id,
            "created_by": self.created_by,
            "display_name": self.display_name,
            "source_type": self.source_type,
            "connector_type": self.connector_type,
            "db_type": self.db_type,
            "host": self.host,
            "port": self.port,
            "database_name": self.database_name,
            "schema_name": self.schema_name,
            "table_name": self.table_name,
            "username": self.username,
            "has_password": bool(self.password_encrypted),
            "ssl_mode": self.ssl_mode,
            "teiid_view_name": self.teiid_view_name,
            "teiid_model_name": self.teiid_model_name,
            "teiid_table_name": self.teiid_table_name,
            "status": self.status,
            "archived": self.archived,
            "archived_at": self.archived_at.isoformat() if self.archived_at else None,
            "last_test_status": self.last_test_status,
            "last_test_message": self.last_test_message,
            "last_tested_at": self.last_tested_at.isoformat()
            if self.last_tested_at
            else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"DatabaseDataSource(id={self.id}, display_name={self.display_name!r}, "
            f"db_type={self.db_type!r}, table={self.table_name!r})"
        )


class DataSourceColumn(Base):
    __tablename__ = "data_source_columns"

    id: Mapped[int] = mapped_column(primary_key=True)
    data_source_id: Mapped[int] = mapped_column(
        ForeignKey("database_data_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    column_name: Mapped[str] = mapped_column(String(255), nullable=False)
    ordinal_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # User-chosen Teiid runtime type that overrides the introspected data_type
    # when the VDB model is (re)registered (e.g. "integer", "date").
    teiid_type_override: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    nullable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    primary_key: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    data_source: Mapped[DatabaseDataSource] = relationship(back_populates="columns")

    def to_dict(self) -> dict:
        return {
            "name": self.column_name,
            "ordinal_position": self.ordinal_position,
            "type": self.teiid_type_override or self.data_type,
            "data_type": self.data_type,
            "teiid_type_override": self.teiid_type_override,
            "nullable": self.nullable,
            "primary_key": self.primary_key,
        }
