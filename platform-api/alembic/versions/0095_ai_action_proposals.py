"""AI action proposal review and grounded outcome fields.

Revision ID: 0095
Revises: 0094
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0095"
down_revision: str | None = "0094"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "project_actions",
        sa.Column("source_surface", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "project_actions",
        sa.Column("reviewer_user_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "project_actions",
        sa.Column("reviewed_by_user_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "project_actions",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "project_actions",
        sa.Column("review_note", sa.Text(), nullable=True),
    )
    op.add_column(
        "project_actions",
        sa.Column("review_due_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "project_actions",
        sa.Column("goal_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "project_actions",
        sa.Column("primary_metric_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "project_actions",
        sa.Column(
            "proposal_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "project_actions",
        sa.Column(
            "outcome_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "project_actions",
        sa.Column("outcome_status", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "project_actions",
        sa.Column("outcome_refreshed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_foreign_key(
        "fk_project_actions_reviewer_user_id",
        "project_actions",
        "users",
        ["reviewer_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_project_actions_reviewed_by_user_id",
        "project_actions",
        "users",
        ["reviewed_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_project_actions_goal_id",
        "project_actions",
        "project_goals",
        ["goal_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_project_actions_primary_metric_id",
        "project_actions",
        "project_metrics",
        ["primary_metric_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_project_actions_reviewer_user_id",
        "project_actions",
        ["reviewer_user_id"],
    )
    op.create_index(
        "ix_project_actions_reviewer_status",
        "project_actions",
        ["reviewer_user_id", "status"],
    )
    op.create_index(
        "ix_project_actions_goal_id",
        "project_actions",
        ["goal_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_project_actions_goal_id", table_name="project_actions")
    op.drop_index("ix_project_actions_reviewer_status", table_name="project_actions")
    op.drop_index("ix_project_actions_reviewer_user_id", table_name="project_actions")
    op.drop_constraint(
        "fk_project_actions_primary_metric_id",
        "project_actions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_project_actions_goal_id",
        "project_actions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_project_actions_reviewed_by_user_id",
        "project_actions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_project_actions_reviewer_user_id",
        "project_actions",
        type_="foreignkey",
    )
    for column in (
        "outcome_refreshed_at",
        "outcome_status",
        "outcome_snapshot",
        "proposal_metadata",
        "primary_metric_id",
        "goal_id",
        "review_due_at",
        "review_note",
        "reviewed_at",
        "reviewed_by_user_id",
        "reviewer_user_id",
        "source_surface",
    ):
        op.drop_column("project_actions", column)
