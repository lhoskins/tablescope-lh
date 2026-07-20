"""insight_feedback_review

Revision ID: 91455ab780b4
Revises: 0060
Create Date: 2026-07-20 16:34:33.681422

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '91455ab780b4'
down_revision: str | None = '0060'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "insight_feedback",
        sa.Column("review_status", sa.String(20), nullable=False, server_default="pending"),
    )
    op.add_column(
        "insight_feedback",
        sa.Column("reviewer_user_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "insight_feedback",
        sa.Column("reviewer_comment", sa.Text(), nullable=True),
    )
    op.add_column(
        "insight_feedback",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_insight_feedback_review_status",
        "insight_feedback",
        ["review_status"],
    )
    op.create_index(
        "ix_insight_feedback_reviewer_user_id",
        "insight_feedback",
        ["reviewer_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_insight_feedback_reviewer_user_id", table_name="insight_feedback")
    op.drop_index("ix_insight_feedback_review_status", table_name="insight_feedback")
    op.drop_column("insight_feedback", "reviewed_at")
    op.drop_column("insight_feedback", "reviewer_comment")
    op.drop_column("insight_feedback", "reviewer_user_id")
    op.drop_column("insight_feedback", "review_status")
