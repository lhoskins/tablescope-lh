"""Project Insight acknowledgements table.

Records that a user reviewed/acknowledged a project insight (who + when). One
row per (project_id, insight_id); re-acknowledging updates the existing row.

Revision ID: 0045
Revises: 0044
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0045"
down_revision: str | None = "0044"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = set(sa.inspect(conn).get_table_names())
    if "project_insight_acknowledgements" in existing:
        return
    op.create_table(
        "project_insight_acknowledgements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("insight_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column(
            "status", sa.String(length=50), nullable=False, server_default="reviewed"
        ),
        sa.Column("note", sa.Text(), nullable=True),
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
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "insight_id", name="uq_project_insight_ack"
        ),
    )
    op.create_index(
        "ix_project_insight_acknowledgements_tenant_id",
        "project_insight_acknowledgements",
        ["tenant_id"],
    )
    op.create_index(
        "ix_project_insight_acknowledgements_project_id",
        "project_insight_acknowledgements",
        ["project_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_project_insight_acknowledgements_project_id",
        table_name="project_insight_acknowledgements",
    )
    op.drop_index(
        "ix_project_insight_acknowledgements_tenant_id",
        table_name="project_insight_acknowledgements",
    )
    op.drop_table("project_insight_acknowledgements")
