"""Multi-table mapping for a single spreadsheet-backed file source.

A single Google Sheets tab (or Excel worksheet) can contain several
independent rectangular tables (see the Google Drive Spreadsheet Connector
implementation plan). ``FileSourceMeta`` models one file -> one Teiid view;
that one-to-one assumption does not fit a tab with N tables, so this table
adds the missing "N ranges live inside 1 file" layer on top of it. Each
confirmed range becomes its own row here and (once Workstream E lands) its
own Teiid view/data source, all sharing the same parent
``FileSourceMeta``/Drive file identity.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

_JSON = JSONB().with_variant(JSON(), "sqlite")

#: How the connected range is kept in sync with the live source as it grows.
RANGE_POLICIES = ("fixed", "dynamic_rows", "dynamic_region", "provider_table")
#: Where the proposed range came from (see plan section 6.1 detection priority).
DETECTION_METHODS = (
    "native_table",
    "named_range",
    "banded_range",
    "connected_region",
    "single_table_fallback",
    "ai_assisted",
    "manual",
)
MAPPING_STATUSES = ("proposed", "confirmed", "schema_drift", "unavailable", "excluded")


class SpreadsheetTableMapping(TimestampMixin, Base):
    __tablename__ = "spreadsheet_table_mappings"
    __table_args__ = (
        UniqueConstraint(
            "file_source_meta_id", "range_a1",
            name="uq_spreadsheet_table_mapping_range",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # The parent file this range lives inside of. One FileSourceMeta row per
    # Drive file/tab combination; many SpreadsheetTableMapping rows per file.
    file_source_meta_id: Mapped[int] = mapped_column(
        ForeignKey("file_source_meta.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # A Teiid view is created for this mapping only once confirmed (Workstream
    # E). Null until then.
    datasource_id: Mapped[int | None] = mapped_column(
        ForeignKey("file_source_meta.id", ondelete="SET NULL"), nullable=True
    )

    sheet_stable_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sheet_name_at_creation: Mapped[str] = mapped_column(String(255), nullable=False)
    table_name: Mapped[str] = mapped_column(String(255), nullable=False)
    range_a1: Mapped[str] = mapped_column(String(128), nullable=False)
    range_policy: Mapped[str] = mapped_column(
        String(20), nullable=False, default="dynamic_rows", server_default="dynamic_rows"
    )
    header_row_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    data_start_row_index: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # A stable fingerprint of the header row's cell values, used to detect
    # that the anchored region has drifted/moved on refresh (see plan
    # section 11, "Column additions or header changes").
    anchor_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)

    detection_method: Mapped[str] = mapped_column(String(30), nullable=False)
    detection_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    user_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    source_revision_at_catalog: Mapped[str | None] = mapped_column(String(255), nullable=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="proposed", server_default="proposed"
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "fileSourceMetaId": self.file_source_meta_id,
            "datasourceId": self.datasource_id,
            "sheetStableId": self.sheet_stable_id,
            "sheetNameAtCreation": self.sheet_name_at_creation,
            "tableName": self.table_name,
            "rangeA1": self.range_a1,
            "rangePolicy": self.range_policy,
            "headerRowIndex": self.header_row_index,
            "dataStartRowIndex": self.data_start_row_index,
            "detectionMethod": self.detection_method,
            "detectionConfidence": self.detection_confidence,
            "userConfirmed": self.user_confirmed,
            "schemaVersion": self.schema_version,
            "status": self.status,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"SpreadsheetTableMapping(id={self.id}, table_name={self.table_name!r}, "
            f"range_a1={self.range_a1!r}, status={self.status!r})"
        )


class SpreadsheetColumnMapping(TimestampMixin, Base):
    __tablename__ = "spreadsheet_column_mappings"
    __table_args__ = (
        UniqueConstraint(
            "table_mapping_id", "ordinal", name="uq_spreadsheet_column_mapping_ordinal"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    table_mapping_id: Mapped[int] = mapped_column(
        ForeignKey("spreadsheet_table_mappings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    source_label: Mapped[str] = mapped_column(String(255), nullable=False)
    physical_column_ref: Mapped[str] = mapped_column(String(16), nullable=False)
    relational_name: Mapped[str] = mapped_column(String(255), nullable=False)
    teiid_type: Mapped[str] = mapped_column(String(30), nullable=False, default="string")
    semantic_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    nullable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    format_hint: Mapped[str | None] = mapped_column(String(50), nullable=True)
    classification: Mapped[str | None] = mapped_column(String(50), nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tableMappingId": self.table_mapping_id,
            "ordinal": self.ordinal,
            "sourceLabel": self.source_label,
            "physicalColumnRef": self.physical_column_ref,
            "relationalName": self.relational_name,
            "teiidType": self.teiid_type,
            "semanticType": self.semantic_type,
            "nullable": self.nullable,
            "formatHint": self.format_hint,
            "classification": self.classification,
        }
