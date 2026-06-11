"""Add is_active to graph nodes/edges for family deactivate/archive lifecycle.

Revision ID: 0021
Revises: 0020
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def _has_column(conn: sa.engine.Connection, table: str, column: str) -> bool:
    insp = sa.inspect(conn)
    if not insp.has_table(table):
        return False
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    conn = op.get_bind()
    for table in ("ai_project_graph_nodes", "ai_project_graph_edges"):
        if sa.inspect(conn).has_table(table) and not _has_column(conn, table, "is_active"):
            op.add_column(
                table,
                sa.Column(
                    "is_active", sa.Boolean, nullable=False, server_default=sa.true(),
                ),
            )


def downgrade() -> None:
    conn = op.get_bind()
    for table in ("ai_project_graph_edges", "ai_project_graph_nodes"):
        if _has_column(conn, table, "is_active"):
            op.drop_column(table, "is_active")
