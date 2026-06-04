"""Add database_connections table (saved DB connection profiles).

Stores reusable, encrypted database credentials so a user can register several
tables from the same database without re-entering host/port/username/password
each time (item 5).

Revision ID: 0010_database_connections
Revises: 0009_file_source_meta
Create Date: 2026-06-20

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_database_connections"
down_revision: Union[str, None] = "0009_file_source_meta"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "database_connections",
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
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("db_type", sa.String(length=50), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("database_name", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("password_encrypted", sa.Text(), nullable=True),
        sa.Column("ssl_mode", sa.String(length=50), nullable=True),
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
        "ix_database_connections_tenant_id", "database_connections", ["tenant_id"]
    )
    op.create_index(
        "ix_database_connections_created_by",
        "database_connections",
        ["created_by"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_database_connections_created_by", table_name="database_connections"
    )
    op.drop_index(
        "ix_database_connections_tenant_id", table_name="database_connections"
    )
    op.drop_table("database_connections")
