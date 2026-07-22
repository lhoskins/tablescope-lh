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


def _tables(conn: sa.engine.Connection) -> set[str]:
    return set(sa.inspect(conn).get_table_names())


def _columns(conn: sa.engine.Connection, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(conn).get_columns(table)}


def _indexes(conn: sa.engine.Connection, table: str) -> set[str]:
    return {idx["name"] for idx in sa.inspect(conn).get_indexes(table)}


def upgrade() -> None:
    conn = op.get_bind()
    if "insight_feedback" not in _tables(conn):
        return
    cols = _columns(conn, "insight_feedback")
    if "review_status" not in cols:
        op.add_column(
            "insight_feedback",
            sa.Column("review_status", sa.String(20), nullable=False, server_default="pending"),
        )
    if "reviewer_user_id" not in cols:
        op.add_column(
            "insight_feedback",
            sa.Column("reviewer_user_id", sa.Integer(), nullable=True),
        )
    if "reviewer_comment" not in cols:
        op.add_column(
            "insight_feedback",
            sa.Column("reviewer_comment", sa.Text(), nullable=True),
        )
    if "reviewed_at" not in cols:
        op.add_column(
            "insight_feedback",
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        )
    idx = _indexes(conn, "insight_feedback")
    if "ix_insight_feedback_review_status" not in idx:
        op.create_index(
            "ix_insight_feedback_review_status",
            "insight_feedback",
            ["review_status"],
        )
    if "ix_insight_feedback_reviewer_user_id" not in idx:
        op.create_index(
            "ix_insight_feedback_reviewer_user_id",
            "insight_feedback",
            ["reviewer_user_id"],
        )


def downgrade() -> None:
    conn = op.get_bind()
    if "insight_feedback" not in _tables(conn):
        return
    cols = _columns(conn, "insight_feedback")
    idx = _indexes(conn, "insight_feedback")
    if "ix_insight_feedback_reviewer_user_id" in idx:
        op.drop_index("ix_insight_feedback_reviewer_user_id", table_name="insight_feedback")
    if "ix_insight_feedback_review_status" in idx:
        op.drop_index("ix_insight_feedback_review_status", table_name="insight_feedback")
    for col in ("reviewed_at", "reviewer_comment", "reviewer_user_id", "review_status"):
        if col in cols:
            op.drop_column("insight_feedback", col)
