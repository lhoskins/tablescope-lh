"""Add insight_feedback table for human feedback on AI-generated insights.

Revision ID: 0054
Revises: 0053
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0054"
down_revision: str | None = "0053"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "insight_feedback",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column("insight_id", sa.String(length=255), nullable=False),
        sa.Column("snapshot_id", sa.String(length=255), nullable=True),
        sa.Column("run_id", sa.String(length=255), nullable=True),
        sa.Column("insight_type", sa.String(length=100), nullable=True),
        sa.Column("sentiment", sa.String(length=20), nullable=False),
        sa.Column("reason_codes", _JSON, nullable=False, server_default="[]"),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("insight_fingerprint", sa.String(length=255), nullable=True),
        sa.Column("card_snapshot", _JSON, nullable=True),
        sa.Column("explanation_snapshot", _JSON, nullable=True),
        sa.Column("model_metadata", _JSON, nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="active",
        ),
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
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_insight_feedback_tenant_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_insight_feedback_user_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_insight_feedback_project_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "user_id",
            "insight_id",
            name="uix_insight_feedback_tenant_user_insight",
        ),
    )
    op.create_index("ix_insight_feedback_tenant_id", "insight_feedback", ["tenant_id"])
    op.create_index("ix_insight_feedback_user_id", "insight_feedback", ["user_id"])
    op.create_index("ix_insight_feedback_project_id", "insight_feedback", ["project_id"])
    op.create_index("ix_insight_feedback_insight_id", "insight_feedback", ["insight_id"])


def downgrade() -> None:
    op.drop_table("insight_feedback")
