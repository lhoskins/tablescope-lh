"""Durable file import jobs, approved network locations, and file provenance.

Revision ID: 0079
Revises: 0078
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0079"
down_revision: str | None = "0078"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

_JSONB = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "network_file_connections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "protocol", sa.String(length=20), nullable=False, server_default="smb"
        ),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False, server_default="445"),
        sa.Column("share_name", sa.String(length=255), nullable=False),
        sa.Column(
            "approved_root_path",
            sa.String(length=1024),
            nullable=False,
            server_default="",
        ),
        sa.Column("domain", sa.String(length=255), nullable=True),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("secret_encrypted", sa.Text(), nullable=True),
        sa.Column(
            "require_signing", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "require_encryption",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_test_status", sa.String(length=50), nullable=True),
        sa.Column("last_test_message_safe", sa.String(length=512), nullable=True),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_network_file_connections_tenant_id",
        "network_file_connections",
        ["tenant_id"],
    )

    op.create_table(
        "file_import_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("requested_by", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("method", sa.String(length=20), nullable=False),
        sa.Column(
            "content_family",
            sa.String(length=20),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="queued"
        ),
        sa.Column("original_file_name", sa.String(length=512), nullable=True),
        sa.Column("sanitized_file_name", sa.String(length=512), nullable=True),
        sa.Column("detected_extension", sa.String(length=20), nullable=True),
        sa.Column("detected_mime_type", sa.String(length=255), nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("storage_key", sa.Text(), nullable=True),
        sa.Column("source_host", sa.String(length=255), nullable=True),
        sa.Column("source_locator_redacted", sa.String(length=1024), nullable=True),
        sa.Column("network_connection_id", sa.Integer(), nullable=True),
        sa.Column("remote_etag", sa.String(length=255), nullable=True),
        sa.Column("remote_last_modified", sa.String(length=255), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("error_message_safe", sa.String(length=1024), nullable=True),
        sa.Column("profile_json", _JSONB, nullable=True),
        sa.Column("result_json", _JSONB, nullable=True),
        sa.Column("finalized_data_source_id", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["network_connection_id"],
            ["network_file_connections.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_file_import_jobs_tenant_id", "file_import_jobs", ["tenant_id"])
    op.create_index(
        "ix_file_import_jobs_requested_by", "file_import_jobs", ["requested_by"]
    )
    op.create_index("ix_file_import_jobs_sha256", "file_import_jobs", ["sha256"])
    op.create_index(
        "ix_file_import_jobs_expires_at", "file_import_jobs", ["expires_at"]
    )
    op.create_index(
        "ix_file_import_jobs_tenant_status", "file_import_jobs", ["tenant_id", "status"]
    )
    op.create_index(
        "ix_file_import_jobs_tenant_requester",
        "file_import_jobs",
        ["tenant_id", "requested_by"],
    )

    op.add_column(
        "file_source_meta",
        sa.Column(
            "acquisition_method",
            sa.String(length=20),
            nullable=False,
            server_default="local_upload",
        ),
    )
    op.add_column(
        "file_source_meta", sa.Column("import_job_id", sa.String(length=36), nullable=True)
    )
    op.add_column(
        "file_source_meta", sa.Column("source_host", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "file_source_meta",
        sa.Column("source_locator_redacted", sa.String(length=1024), nullable=True),
    )
    op.add_column(
        "file_source_meta",
        sa.Column("network_connection_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "file_source_meta", sa.Column("content_sha256", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "file_source_meta", sa.Column("remote_etag", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "file_source_meta",
        sa.Column("remote_last_modified", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "file_source_meta",
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_file_source_meta_network_connection",
        "file_source_meta",
        "network_file_connections",
        ["network_connection_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_file_source_meta_network_connection",
        "file_source_meta",
        type_="foreignkey",
    )
    for column in (
        "retrieved_at",
        "remote_last_modified",
        "remote_etag",
        "content_sha256",
        "network_connection_id",
        "source_locator_redacted",
        "source_host",
        "import_job_id",
        "acquisition_method",
    ):
        op.drop_column("file_source_meta", column)

    op.drop_index("ix_file_import_jobs_tenant_requester", table_name="file_import_jobs")
    op.drop_index("ix_file_import_jobs_tenant_status", table_name="file_import_jobs")
    op.drop_index("ix_file_import_jobs_expires_at", table_name="file_import_jobs")
    op.drop_index("ix_file_import_jobs_sha256", table_name="file_import_jobs")
    op.drop_index("ix_file_import_jobs_requested_by", table_name="file_import_jobs")
    op.drop_index("ix_file_import_jobs_tenant_id", table_name="file_import_jobs")
    op.drop_table("file_import_jobs")

    op.drop_index(
        "ix_network_file_connections_tenant_id", table_name="network_file_connections"
    )
    op.drop_table("network_file_connections")
