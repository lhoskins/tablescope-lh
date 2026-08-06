"""Add network_file_hosts allowlist table.

Revision ID: 0081
Revises: 0080
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0081"
down_revision: str | None = "0080"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "network_file_hosts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
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
        sa.UniqueConstraint("tenant_id", "host", name="uq_network_file_hosts_tenant_host"),
    )
    op.create_index(
        "ix_network_file_hosts_tenant_id",
        "network_file_hosts",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_network_file_hosts_tenant_id", table_name="network_file_hosts")
    op.drop_table("network_file_hosts")
