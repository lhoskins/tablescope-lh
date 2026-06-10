"""Create project_assets table for unstructured documents.

Revision ID: 0020
Revises: 0019
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def _table_exists(conn: sa.engine.Connection, name: str) -> bool:
    return sa.inspect(conn).has_table(name)


def upgrade() -> None:
    conn = op.get_bind()

    if not _table_exists(conn, "project_assets"):
        op.create_table(
            "project_assets",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("owner_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("asset_type", sa.String(100), nullable=False),
            sa.Column("source_type", sa.String(100), nullable=False, server_default="uploaded_file"),
            sa.Column("title", sa.Text, nullable=False),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("filename", sa.Text, nullable=False),
            sa.Column("original_filename", sa.Text, nullable=True),
            sa.Column("content_type", sa.String(255), nullable=True),
            sa.Column("file_extension", sa.String(50), nullable=True),
            sa.Column("storage_provider", sa.String(50), nullable=False, server_default="local"),
            sa.Column("storage_location", sa.Text, nullable=False),
            sa.Column("file_hash", sa.Text, nullable=True),
            sa.Column("file_size_bytes", sa.BigInteger, nullable=True),
            sa.Column("visibility", sa.String(50), nullable=False, server_default="shared_project"),
            sa.Column("access_group_id", sa.Integer, nullable=True),
            sa.Column("status", sa.String(50), nullable=False, server_default="uploaded"),
            sa.Column("ai_status", sa.String(50), nullable=False, server_default="pending"),
            sa.Column("ai_summary", sa.Text, nullable=True),
            sa.Column("ai_metadata", JSONB, nullable=False, server_default="{}"),
            sa.Column("ai_error_message", sa.Text, nullable=True),
            sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("idx_project_assets_tenant_project", "project_assets", ["tenant_id", "project_id"])
        op.create_index("idx_project_assets_owner", "project_assets", ["owner_user_id"])
        op.create_index("idx_project_assets_asset_type", "project_assets", ["asset_type"])
        op.create_index("idx_project_assets_ai_status", "project_assets", ["ai_status"])


def downgrade() -> None:
    op.drop_table("project_assets")
