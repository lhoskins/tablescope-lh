"""Extend project actions for Monday-style workspace.

Revision ID: 0069
Revises: 0068
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0069"
down_revision: str | None = "0068"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column(
        "project_actions",
        sa.Column(
            "lock_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.add_column(
        "project_action_subtasks",
        sa.Column(
            "lock_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.add_column(
        "project_action_subtasks",
        sa.Column(
            "effort_points",
            sa.SmallInteger(),
            nullable=True,
        ),
    )
    op.add_column(
        "project_action_subtasks",
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_subtask_effort_points",
        "project_action_subtasks",
        sa.text("effort_points IS NULL OR (effort_points >= 1 AND effort_points <= 10)"),
    )

    op.create_table(
        "project_action_comments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "action_id",
            sa.Integer(),
            sa.ForeignKey("project_actions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "author_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "archived_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_project_action_comments_action_created",
        "project_action_comments",
        ["tenant_id", "project_id", "action_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_project_action_comments_action_created",
        table_name="project_action_comments",
    )
    op.drop_table("project_action_comments")
    op.drop_column("project_action_subtasks", "completed_at")
    op.drop_column("project_action_subtasks", "effort_points")
    op.drop_column("project_action_subtasks", "lock_version")
    op.drop_column("project_actions", "lock_version")
