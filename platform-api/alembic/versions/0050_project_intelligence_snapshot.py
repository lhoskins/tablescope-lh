"""Project Insight per-project snapshot table.

Persists the latest completed Project Insight run per (tenant, user, project)
so the page hydrates instantly on open while a fresh run rebuilds in the
background. One row per (tenant, user, project); a new run overwrites it.

Revision ID: 0050
Revises: 0049
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0050"
down_revision: str | None = "0049"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    conn = op.get_bind()
    existing = set(sa.inspect(conn).get_table_names())
    if "project_intelligence_snapshots" in existing:
        return
    op.create_table(
        "project_intelligence_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("payload", _JSON, nullable=False),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "user_id",
            "project_id",
            name="uq_project_intelligence_snapshot",
        ),
    )
    op.create_index(
        "ix_project_intelligence_snapshots_tenant_id",
        "project_intelligence_snapshots",
        ["tenant_id"],
    )
    op.create_index(
        "ix_project_intelligence_snapshots_user_id",
        "project_intelligence_snapshots",
        ["user_id"],
    )
    op.create_index(
        "ix_project_intelligence_snapshots_project_id",
        "project_intelligence_snapshots",
        ["project_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_project_intelligence_snapshots_project_id",
        table_name="project_intelligence_snapshots",
    )
    op.drop_index(
        "ix_project_intelligence_snapshots_user_id",
        table_name="project_intelligence_snapshots",
    )
    op.drop_index(
        "ix_project_intelligence_snapshots_tenant_id",
        table_name="project_intelligence_snapshots",
    )
    op.drop_table("project_intelligence_snapshots")
