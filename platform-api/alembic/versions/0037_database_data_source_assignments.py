"""DB Admin data source assignments (issue 5).

Creates ``database_data_source_assignments`` so an Admin / DB Admin can grant a
user access to an already-configured database datasource (the credentials stay
hidden; the connector is inherited from the assigned datasource).

Revision ID: 0037
Revises: 0036
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = set(sa.inspect(conn).get_table_names())
    if "database_data_source_assignments" in existing:
        return
    op.create_table(
        "database_data_source_assignments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("database_data_source_id", sa.Integer(), nullable=False),
        sa.Column("database_connection_id", sa.Integer(), nullable=True),
        sa.Column("assigned_user_id", sa.Integer(), nullable=False),
        sa.Column("friendly_name", sa.String(length=255), nullable=False),
        sa.Column(
            "read_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("assigned_by", sa.Integer(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["database_data_source_id"],
            ["database_data_sources.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["database_connection_id"],
            ["database_connections.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["assigned_by"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "database_data_source_id",
            "assigned_user_id",
            name="uq_dds_assignment_tenant_source_user",
        ),
    )
    op.create_index(
        "ix_database_data_source_assignments_tenant_id",
        "database_data_source_assignments",
        ["tenant_id"],
    )
    op.create_index(
        "ix_database_data_source_assignments_database_data_source_id",
        "database_data_source_assignments",
        ["database_data_source_id"],
    )
    op.create_index(
        "ix_database_data_source_assignments_assigned_user_id",
        "database_data_source_assignments",
        ["assigned_user_id"],
    )


def downgrade() -> None:
    op.drop_table("database_data_source_assignments")
