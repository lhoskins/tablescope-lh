"""KG-20: reference document expiration date.

Adds ``expiration_date`` to ``reference_documents`` so a version of
authoritative guidance can stop being treated as current on a known date,
even without an explicit supersession record -- collect_structural_graph
excludes expired documents from the active reference set.

Revision ID: 0090
Revises: 0089
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0090"
down_revision: str | None = "0089"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def _has_column(conn: sa.engine.Connection, table: str, column: str) -> bool:
    return any(c["name"] == column for c in sa.inspect(conn).get_columns(table))


def upgrade() -> None:
    conn = op.get_bind()
    if _has_column(conn, "reference_documents", "expiration_date"):
        return
    op.add_column(
        "reference_documents",
        sa.Column("expiration_date", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("reference_documents", "expiration_date")
