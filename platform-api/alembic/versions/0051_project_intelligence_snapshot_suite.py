"""Add suite column to project intelligence snapshots.

Revision ID: 0051
Revises: 0050
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0051"
down_revision: str | None = "0050"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    columns = {c["name"] for c in sa.inspect(conn).get_columns("project_intelligence_snapshots")}

    if "suite" not in columns:
        op.add_column(
            "project_intelligence_snapshots",
            sa.Column("suite", sa.String(length=50), nullable=False, server_default="project_insight"),
        )

    op.drop_constraint(
        "uq_project_intelligence_snapshot",
        "project_intelligence_snapshots",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_project_intelligence_snapshot",
        "project_intelligence_snapshots",
        ["tenant_id", "user_id", "project_id", "suite"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_project_intelligence_snapshot",
        "project_intelligence_snapshots",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_project_intelligence_snapshot",
        "project_intelligence_snapshots",
        ["tenant_id", "user_id", "project_id"],
    )
    op.drop_column("project_intelligence_snapshots", "suite")
