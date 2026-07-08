"""Add last_tested_at to saved connection profiles.

Database Connectors surfaces a "Last Tested" column for each saved connection
profile (database connections and SaaS connector credentials). Persist the
timestamp so it survives across sessions and reflects the most recent verify.

Revision ID: 0033
Revises: 0032
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

_COL = "last_tested_at"
_TABLES = ("database_connections", "connector_credentials")


def _has_column(conn: sa.engine.Connection, table: str, column: str) -> bool:
    insp = sa.inspect(conn)
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    conn = op.get_bind()
    for table in _TABLES:
        if not _has_column(conn, table, _COL):
            op.add_column(
                table,
                sa.Column(_COL, sa.DateTime(timezone=True), nullable=True),
            )


def downgrade() -> None:
    conn = op.get_bind()
    for table in _TABLES:
        if _has_column(conn, table, _COL):
            op.drop_column(table, _COL)
