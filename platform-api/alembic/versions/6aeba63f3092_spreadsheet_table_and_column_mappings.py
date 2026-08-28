"""spreadsheet table and column mappings

Revision ID: 6aeba63f3092
Revises: c4d92a811e01
Create Date: 2026-08-28

Adds the multi-table-per-file layer the Google Drive Spreadsheet Connector
plan needs: FileSourceMeta models one file/tab -> one Teiid view, which does
not fit a tab containing several independent tables. Each confirmed range
becomes its own SpreadsheetTableMapping row (optionally later its own
FileSourceMeta-backed Teiid view via datasource_id), with its columns in
SpreadsheetColumnMapping.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "6aeba63f3092"
down_revision: str | None = "c4d92a811e01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "spreadsheet_table_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column(
            "file_source_meta_id", sa.Integer(),
            sa.ForeignKey("file_source_meta.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "datasource_id", sa.Integer(),
            sa.ForeignKey("file_source_meta.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("sheet_stable_id", sa.String(64), nullable=True),
        sa.Column("sheet_name_at_creation", sa.String(255), nullable=False),
        sa.Column("table_name", sa.String(255), nullable=False),
        sa.Column("range_a1", sa.String(128), nullable=False),
        sa.Column("range_policy", sa.String(20), nullable=False, server_default="dynamic_rows"),
        sa.Column("header_row_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("data_start_row_index", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("anchor_fingerprint", sa.String(64), nullable=True),
        sa.Column("detection_method", sa.String(30), nullable=False),
        sa.Column("detection_confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("user_confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("source_revision_at_catalog", sa.String(255), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(20), nullable=False, server_default="proposed"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "file_source_meta_id", "range_a1", name="uq_spreadsheet_table_mapping_range",
        ),
    )
    for name in ("tenant_id", "project_id", "file_source_meta_id", "datasource_id"):
        op.create_index(
            f"ix_spreadsheet_table_mappings_{name}", "spreadsheet_table_mappings", [name],
        )

    op.create_table(
        "spreadsheet_column_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "table_mapping_id", sa.Integer(),
            sa.ForeignKey("spreadsheet_table_mappings.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("source_label", sa.String(255), nullable=False),
        sa.Column("physical_column_ref", sa.String(16), nullable=False),
        sa.Column("relational_name", sa.String(255), nullable=False),
        sa.Column("teiid_type", sa.String(30), nullable=False, server_default="string"),
        sa.Column("semantic_type", sa.String(50), nullable=True),
        sa.Column("nullable", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("format_hint", sa.String(50), nullable=True),
        sa.Column("classification", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "table_mapping_id", "ordinal", name="uq_spreadsheet_column_mapping_ordinal",
        ),
    )
    op.create_index(
        "ix_spreadsheet_column_mappings_table_mapping_id",
        "spreadsheet_column_mappings", ["table_mapping_id"],
    )


def downgrade() -> None:
    op.drop_table("spreadsheet_column_mappings")
    op.drop_table("spreadsheet_table_mappings")
