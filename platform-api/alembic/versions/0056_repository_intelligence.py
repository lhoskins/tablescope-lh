"""Add repository intelligence tables for Sprint 06.

Revision ID: 0056
Revises: 0055
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0056"
down_revision: str | None = "0055"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "repository_connections",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("connector_type", sa.String(50), nullable=False, index=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column("config_json", _JSON, nullable=False, server_default="{}"),
        sa.Column(
            "credential_id",
            sa.Integer(),
            sa.ForeignKey("connector_credentials.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("scan_schedule", sa.String(50), nullable=True),
        sa.Column(
            "last_scan_id",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column("last_successful_scan_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
        "ix_repository_connections_tenant_enabled",
        "repository_connections",
        ["tenant_id", "is_enabled"],
    )

    op.create_table(
        "repository_scans",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("repository_connections.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("trigger_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="queued"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checkpoint_json", _JSON, nullable=True),
        sa.Column("files_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("directories_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bytes_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("added_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("changed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deleted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("worker_id", sa.String(255), nullable=True),
        sa.Column("retry_attempt", sa.Integer(), nullable=False, server_default="0"),
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
        "ix_repository_scans_status_heartbeat",
        "repository_scans",
        ["status", "heartbeat_at"],
    )

    op.create_table(
        "repository_items",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("repository_connections.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("external_id", sa.String(255), nullable=False, index=True),
        sa.Column("relative_path", sa.String(2048), nullable=False),
        sa.Column("name", sa.String(1024), nullable=False),
        sa.Column("parent_path", sa.String(2048), nullable=False, server_default="/"),
        sa.Column("item_type", sa.String(50), nullable=False),
        sa.Column("extension", sa.String(255), nullable=True),
        sa.Column("mime_type", sa.String(255), nullable=True),
        sa.Column("size", sa.Integer(), nullable=True),
        sa.Column("source_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("etag", sa.String(255), nullable=True),
        sa.Column("content_hash", sa.String(255), nullable=True),
        sa.Column("metadata_json", _JSON, nullable=False, server_default="{}"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "first_seen_scan_id",
            sa.Integer(),
            sa.ForeignKey("repository_scans.id"),
            nullable=True,
        ),
        sa.Column(
            "last_seen_scan_id",
            sa.Integer(),
            sa.ForeignKey("repository_scans.id"),
            nullable=True,
        ),
        sa.Column(
            "last_changed_scan_id",
            sa.Integer(),
            sa.ForeignKey("repository_scans.id"),
            nullable=True,
        ),
        sa.Column(
            "extraction_status",
            sa.String(50),
            nullable=False,
            server_default="pending",
        ),
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
    with op.batch_alter_table("repository_items") as batch_op:
        batch_op.create_unique_constraint(
            "uq_repository_item_connection_external",
            ["connection_id", "external_id"],
        )
    op.create_index(
        "ix_repository_items_path", "repository_items", ["connection_id", "relative_path"]
    )
    op.create_index(
        "ix_repository_items_last_seen",
        "repository_items",
        ["connection_id", "last_seen_scan_id"],
    )
    op.create_index(
        "ix_repository_items_extraction",
        "repository_items",
        ["connection_id", "extraction_status"],
    )
    op.create_index(
        "ix_repository_items_deleted",
        "repository_items",
        ["connection_id", "is_deleted"],
    )

    op.create_table(
        "repository_profiles",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("repository_connections.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "scan_id",
            sa.Integer(),
            sa.ForeignKey("repository_scans.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("profile_json", _JSON, nullable=False, server_default="{}"),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default="true"),
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
        "ix_repository_profiles_current",
        "repository_profiles",
        ["connection_id", "is_current"],
    )


def downgrade() -> None:
    op.drop_index("ix_repository_profiles_current", table_name="repository_profiles")
    op.drop_table("repository_profiles")
    op.drop_index("ix_repository_items_deleted", table_name="repository_items")
    op.drop_index("ix_repository_items_extraction", table_name="repository_items")
    op.drop_index("ix_repository_items_last_seen", table_name="repository_items")
    op.drop_index("ix_repository_items_path", table_name="repository_items")
    with op.batch_alter_table("repository_items") as batch_op:
        batch_op.drop_constraint(
            "uq_repository_item_connection_external",
            type_="unique",
        )
    op.drop_table("repository_items")
    op.drop_index("ix_repository_scans_status_heartbeat", table_name="repository_scans")
    op.drop_table("repository_scans")
    op.drop_index("ix_repository_connections_tenant_enabled", table_name="repository_connections")
    op.drop_table("repository_connections")
