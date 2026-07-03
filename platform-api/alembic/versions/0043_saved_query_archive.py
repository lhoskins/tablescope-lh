"""Saved query archive lifecycle columns.

Adds ``is_archived``, ``archived_at`` and ``archived_by`` to ``saved_queries``
so a query can be archived (hidden from normal lists but still executable) and
only permanently deleted after archiving + dependency removal.

Revision ID: 0043
Revises: 0042
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    cols = {c["name"] for c in sa.inspect(conn).get_columns("saved_queries")}
    if "is_archived" not in cols:
        op.add_column(
            "saved_queries",
            sa.Column(
                "is_archived",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
    if "archived_at" not in cols:
        op.add_column(
            "saved_queries",
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "archived_by" not in cols:
        op.add_column(
            "saved_queries",
            sa.Column("archived_by", sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("saved_queries", "archived_by")
    op.drop_column("saved_queries", "archived_at")
    op.drop_column("saved_queries", "is_archived")
