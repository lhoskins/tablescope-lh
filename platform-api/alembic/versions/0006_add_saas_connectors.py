"""Add SaaS connector tables + connector_type on database_data_sources.

Adds:
* ``connector_credentials`` — encrypted SaaS auth material (HubSpot token,
  Salesforce OAuth bundle), reusable across objects.
* ``saas_object_data_sources`` — per-object SaaS metadata + sync state, linked
  to the ``DatabaseDataSource`` that exposes its staging table to Teiid.
* ``database_data_sources.connector_type`` — so the UI can badge SaaS-backed
  sources even though their staging table is plain Postgres.

Revision ID: 0006_saas_connectors
Revises: 0005_db_sources
Create Date: 2026-06-01

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0006_saas_connectors"
down_revision: Union[str, None] = "0005_db_sources"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "database_data_sources",
        sa.Column("connector_type", sa.String(length=50), nullable=True),
    )

    op.create_table(
        "connector_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("connector_type", sa.String(length=50), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("secret_encrypted", sa.Text(), nullable=True),
        sa.Column("config_json", sa.Text(), nullable=True),
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
        "ix_connector_credentials_tenant_id",
        "connector_credentials",
        ["tenant_id"],
    )

    op.create_table(
        "saas_object_data_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "database_data_source_id",
            sa.Integer(),
            sa.ForeignKey("database_data_sources.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "credential_id",
            sa.Integer(),
            sa.ForeignKey("connector_credentials.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("connector_type", sa.String(length=50), nullable=False),
        sa.Column("object_type", sa.String(length=100), nullable=False),
        sa.Column("selected_properties", JSONB(), nullable=False),
        sa.Column("staging_schema", sa.String(length=255), nullable=False),
        sa.Column("staging_table", sa.String(length=255), nullable=False),
        sa.Column(
            "sync_mode", sa.String(length=50), nullable=False, server_default="manual"
        ),
        sa.Column("last_sync_status", sa.String(length=50), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_message", sa.Text(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
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
        "ix_saas_object_data_sources_tenant_id",
        "saas_object_data_sources",
        ["tenant_id"],
    )
    op.create_index(
        "ix_saas_object_data_sources_credential_id",
        "saas_object_data_sources",
        ["credential_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_saas_object_data_sources_credential_id",
        table_name="saas_object_data_sources",
    )
    op.drop_index(
        "ix_saas_object_data_sources_tenant_id",
        table_name="saas_object_data_sources",
    )
    op.drop_table("saas_object_data_sources")
    op.drop_index(
        "ix_connector_credentials_tenant_id", table_name="connector_credentials"
    )
    op.drop_table("connector_credentials")
    op.drop_column("database_data_sources", "connector_type")
