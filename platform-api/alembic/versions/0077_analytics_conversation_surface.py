"""Add surface column to analytics_conversations.

Revision ID: 0077
Revises: 0076
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0077"
down_revision: str | None = "0076"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column(
        "analytics_conversations",
        sa.Column(
            "surface",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'ai_assistant'"),
        ),
    )
    op.create_index(
        "ix_analytics_conversations_surface_project",
        "analytics_conversations",
        ["tenant_id", "user_id", "surface", "project_id"],
    )
    op.execute(
        "UPDATE analytics_conversations SET surface = 'ai_assistant' WHERE surface IS NULL"
    )


def downgrade() -> None:
    op.drop_index(
        "ix_analytics_conversations_surface_project",
        table_name="analytics_conversations",
    )
    op.drop_column("analytics_conversations", "surface")
