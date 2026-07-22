"""Widen insight_feedback review status columns.

Revision ID: 0064
Revises: 0063
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0064"
down_revision: str | None = "0063"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def _column_length(conn: sa.engine.Connection, table: str, column: str) -> int | None:
    """Return the current character_maximum_length for a column, or None."""
    row = conn.execute(
        sa.text(
            """
            SELECT character_maximum_length
            FROM information_schema.columns
            WHERE table_name = :table_name AND column_name = :column_name
            """
        ),
        {"table_name": table, "column_name": column},
    ).fetchone()
    return row[0] if row else None


def _table_exists(conn: sa.engine.Connection, table: str) -> bool:
    return table in set(sa.inspect(conn).get_table_names())


def upgrade() -> None:
    conn = op.get_bind()

    if _table_exists(conn, "insight_feedback"):
        length = _column_length(conn, "insight_feedback", "review_status")
        if length is not None and length < 50:
            op.alter_column(
                "insight_feedback",
                "review_status",
                type_=sa.String(50),
                nullable=False,
            )

    if _table_exists(conn, "insight_feedback_review_events"):
        for col in ("from_review_status", "to_review_status"):
            length = _column_length(conn, "insight_feedback_review_events", col)
            if length is not None and length < 50:
                op.alter_column(
                    "insight_feedback_review_events",
                    col,
                    type_=sa.String(50),
                    nullable=True,
                )


def downgrade() -> None:
    conn = op.get_bind()

    if _table_exists(conn, "insight_feedback_review_events"):
        for col in ("from_review_status", "to_review_status"):
            length = _column_length(conn, "insight_feedback_review_events", col)
            if length is not None and length > 20:
                op.alter_column(
                    "insight_feedback_review_events",
                    col,
                    type_=sa.String(20),
                    nullable=True,
                )

    if _table_exists(conn, "insight_feedback"):
        length = _column_length(conn, "insight_feedback", "review_status")
        if length is not None and length > 20:
            op.alter_column(
                "insight_feedback",
                "review_status",
                type_=sa.String(20),
                nullable=False,
            )
