"""Add file_source_meta table.

Layers Tablescope metadata on top of uploaded-file VDB views so a file data
source can be associated with a project (item 3), soft-archived/deleted
(item 1), and remember per-column formatting hints (item 6).

Revision ID: 0009_file_source_meta
Revises: 0008_grid_prefs_archive
Create Date: 2026-06-16

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_file_source_meta"
down_revision: Union[str, None] = "0008_grid_prefs_archive"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "file_source_meta",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "owner_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("view_name", sa.String(length=255), nullable=False),
        sa.Column("file_name", sa.String(length=512), nullable=False),
        sa.Column(
            "vdb_type", sa.String(length=50), nullable=False, server_default="user"
        ),
        sa.Column(
            "archived", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("column_types", postgresql.JSONB(), nullable=True),
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
        "ix_file_source_meta_tenant_id", "file_source_meta", ["tenant_id"]
    )
    op.create_index(
        "ix_file_source_meta_owner_id", "file_source_meta", ["owner_id"]
    )
    op.create_index(
        "ix_file_source_meta_project_id", "file_source_meta", ["project_id"]
    )
    op.create_index(
        "ix_file_source_meta_view_name", "file_source_meta", ["view_name"]
    )
    op.create_unique_constraint(
        "uq_file_source_view",
        "file_source_meta",
        ["tenant_id", "owner_id", "view_name"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_file_source_view", "file_source_meta", type_="unique"
    )
    op.drop_index("ix_file_source_meta_view_name", table_name="file_source_meta")
    op.drop_index("ix_file_source_meta_project_id", table_name="file_source_meta")
    op.drop_index("ix_file_source_meta_owner_id", table_name="file_source_meta")
    op.drop_index("ix_file_source_meta_tenant_id", table_name="file_source_meta")
    op.drop_table("file_source_meta")
