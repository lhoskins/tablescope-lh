"""Add saved_queries table and is_super_admin flag.

Revision ID: 0003_saved_queries
Revises: 0002_add_password_hash
Create Date: 2026-05-25

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_saved_queries"
down_revision: Union[str, None] = "0002_add_password_hash"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add is_super_admin flag to users
    op.add_column(
        "users",
        sa.Column("is_super_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    # Create saved_queries table
    op.create_table(
        "saved_queries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "owner_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("left_datasource", sa.String(512), nullable=True),
        sa.Column("right_datasource", sa.String(512), nullable=True),
        sa.Column("join_type", sa.String(50), nullable=True),
        sa.Column("left_column", sa.String(255), nullable=True),
        sa.Column("right_column", sa.String(255), nullable=True),
        sa.Column("sql_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_saved_queries_project_id", "saved_queries", ["project_id"])

    # Mark the default admin as super_admin
    op.execute("UPDATE users SET is_super_admin = true WHERE email = 'admin@tablescope.local'")


def downgrade() -> None:
    op.drop_table("saved_queries")
    op.drop_column("users", "is_super_admin")
