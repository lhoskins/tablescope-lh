"""insight_feedback_review_events

Revision ID: 0061
Revises: 91455ab780b4
Create Date: 2026-07-22 02:10:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0061"
down_revision: str | None = "91455ab780b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "insight_feedback",
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "insight_feedback",
        sa.Column("feedback_revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "insight_feedback",
        sa.Column("response", sa.Text(), nullable=True),
    )

    op.create_table(
        "insight_feedback_review_events",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
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
            nullable=True,
            index=True,
        ),
        sa.Column(
            "feedback_id",
            sa.Integer(),
            sa.ForeignKey("insight_feedback.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("insight_id", sa.String(255), nullable=False, index=True),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("from_review_status", sa.String(20), nullable=True),
        sa.Column("to_review_status", sa.String(20), nullable=True),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("response", sa.Text(), nullable=True),
        sa.Column(
            "feedback_revision",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
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
    )


def downgrade() -> None:
    op.drop_table("insight_feedback_review_events")
    op.drop_column("insight_feedback", "feedback_revision")
    op.drop_column("insight_feedback", "acknowledged_at")
