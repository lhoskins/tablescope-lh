"""Add deleted_at column to project_actions.

Revision ID: 0078
Revises: 0077
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0078"
down_revision: str | None = "0077"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column(
        "project_actions",
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_project_actions_deleted_at",
        "project_actions",
        ["deleted_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_project_actions_deleted_at", table_name="project_actions")
    op.drop_column("project_actions", "deleted_at")
