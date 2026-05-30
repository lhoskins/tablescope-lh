"""Add database_data_sources and data_source_columns tables.

Revision ID: 0005_db_sources
Revises: 0004_member_active
Create Date: 2026-05-13

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_db_sources"
down_revision: Union[str, None] = "0004_member_active"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "database_data_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column(
            "source_type",
            sa.String(length=50),
            nullable=False,
            server_default="database_table",
        ),
        sa.Column("db_type", sa.String(length=50), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("database_name", sa.String(length=255), nullable=False),
        sa.Column("schema_name", sa.String(length=255), nullable=True),
        sa.Column("table_name", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("password_encrypted", sa.Text(), nullable=True),
        sa.Column("ssl_mode", sa.String(length=50), nullable=True),
        sa.Column("teiid_model_name", sa.String(length=255), nullable=False),
        sa.Column("teiid_table_name", sa.String(length=255), nullable=False),
        sa.Column("teiid_view_name", sa.String(length=255), nullable=False),
        sa.Column("teiid_jndi_name", sa.String(length=255), nullable=False),
        sa.Column(
            "status", sa.String(length=50), nullable=False, server_default="draft"
        ),
        sa.Column("last_test_status", sa.String(length=50), nullable=True),
        sa.Column("last_test_message", sa.Text(), nullable=True),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_database_data_sources_tenant_id",
        "database_data_sources",
        ["tenant_id"],
    )
    op.create_index(
        "ix_database_data_sources_project_id",
        "database_data_sources",
        ["project_id"],
    )

    op.create_table(
        "data_source_columns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "data_source_id",
            sa.Integer(),
            sa.ForeignKey("database_data_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("column_name", sa.String(length=255), nullable=False),
        sa.Column("ordinal_position", sa.Integer(), nullable=True),
        sa.Column("data_type", sa.String(length=255), nullable=True),
        sa.Column("nullable", sa.Boolean(), nullable=True),
        sa.Column(
            "primary_key", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_data_source_columns_data_source_id",
        "data_source_columns",
        ["data_source_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_data_source_columns_data_source_id", table_name="data_source_columns"
    )
    op.drop_table("data_source_columns")
    op.drop_index(
        "ix_database_data_sources_project_id", table_name="database_data_sources"
    )
    op.drop_index(
        "ix_database_data_sources_tenant_id", table_name="database_data_sources"
    )
    op.drop_table("database_data_sources")
