"""SaaS object data source model.

A ``SaasObjectDataSource`` is the SaaS-specific companion to a
``DatabaseDataSource``.  SaaS apps (HubSpot, Salesforce) are not databases, so we
*sync* a selected object (e.g. HubSpot ``contacts``) into a local Postgres
staging table and then register that staging table in Teiid through the exact
same database-table pipeline.  This row holds the SaaS metadata (which object,
which fields, sync state) and points at:

* the ``ConnectorCredential`` used to talk to the SaaS API, and
* the ``DatabaseDataSource`` that exposes the staging table to Teiid / the query
  builder.

Keeping the Teiid-facing record as a ``DatabaseDataSource`` means listing,
reconciliation-on-restart, deletion and the query path all work unchanged — a
synced HubSpot object behaves exactly like any other table.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

# JSONB on Postgres, plain JSON on other dialects (e.g. SQLite used in tests).
_JSON = JSONB().with_variant(JSON(), "sqlite")


class SaasObjectDataSource(TimestampMixin, Base):
    __tablename__ = "saas_object_data_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The Teiid-facing data source backed by the staging table.
    database_data_source_id: Mapped[int] = mapped_column(
        ForeignKey("database_data_sources.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    credential_id: Mapped[int] = mapped_column(
        ForeignKey("connector_credentials.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    connector_type: Mapped[str] = mapped_column(String(50), nullable=False)
    object_type: Mapped[str] = mapped_column(String(100), nullable=False)
    # List of selected property/field names (JSON array).
    selected_properties: Mapped[list] = mapped_column(_JSON, nullable=False)

    staging_schema: Mapped[str] = mapped_column(String(255), nullable=False)
    staging_table: Mapped[str] = mapped_column(String(255), nullable=False)

    sync_mode: Mapped[str] = mapped_column(
        String(50), nullable=False, default="manual"
    )
    last_sync_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_sync_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "database_data_source_id": self.database_data_source_id,
            "credential_id": self.credential_id,
            "connector_type": self.connector_type,
            "object_type": self.object_type,
            "selected_properties": self.selected_properties,
            "staging_schema": self.staging_schema,
            "staging_table": self.staging_table,
            "sync_mode": self.sync_mode,
            "last_sync_status": self.last_sync_status,
            "last_sync_at": self.last_sync_at.isoformat()
            if self.last_sync_at
            else None,
            "last_sync_message": self.last_sync_message,
            "row_count": self.row_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"SaasObjectDataSource(id={self.id}, "
            f"connector_type={self.connector_type!r}, "
            f"object_type={self.object_type!r}, "
            f"staging_table={self.staging_table!r})"
        )
