"""Add file_source_version table for data-source update versioning.

Revision ID: 0080
Revises: 0079
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0080"
down_revision: str | None = "0079"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "file_source_version",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "file_source_id",
            sa.Integer(),
            sa.ForeignKey("file_source_meta.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "uploader_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("update_mode", sa.String(length=32), nullable=False),
        sa.Column("original_filename", sa.String(length=512), nullable=False),
        sa.Column("stored_path", sa.String(length=1024), nullable=True),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("column_types", sa.JSON(), nullable=True),
        sa.Column("compatibility", sa.JSON(), nullable=True),
        sa.Column(
            "replaced_version_id",
            sa.Integer(),
            sa.ForeignKey("file_source_version.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.String(length=1024), nullable=True),
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
        "ix_file_source_version_tenant_id", "file_source_version", ["tenant_id"]
    )
    op.create_index(
        "ix_file_source_version_file_source_id",
        "file_source_version",
        ["file_source_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_file_source_version_file_source_id", "file_source_version")
    op.drop_index("ix_file_source_version_tenant_id", "file_source_version")
    op.drop_table("file_source_version")
