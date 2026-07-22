"""Add execution engine and chart contract columns to analytical_methods.

Revision ID: 0050
Revises: 0049
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0050"
down_revision: str | None = "0049"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")


def _table_exists(conn: sa.engine.Connection, table: str) -> bool:
    return table in set(sa.inspect(conn).get_table_names())


def _columns(conn: sa.engine.Connection, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(conn).get_columns(table)}


def upgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn, "analytical_methods"):
        return

    cols = _columns(conn, "analytical_methods")

    if "execution_engine" not in cols:
        op.add_column(
            "analytical_methods",
            sa.Column("execution_engine", sa.String(50), nullable=False, server_default="python"),
        )
    if "result_schema_version" not in cols:
        op.add_column(
            "analytical_methods",
            sa.Column("result_schema_version", sa.Integer(), nullable=False, server_default="1"),
        )
    if "chart_contract" not in cols:
        op.add_column(
            "analytical_methods",
            sa.Column("chart_contract", _JSON, nullable=False, server_default="{}"),
        )
    if "max_rows" not in cols:
        op.add_column(
            "analytical_methods",
            sa.Column("max_rows", sa.Integer(), nullable=True),
        )
    if "timeout_seconds" not in cols:
        op.add_column(
            "analytical_methods",
            sa.Column("timeout_seconds", sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn, "analytical_methods"):
        return

    cols = _columns(conn, "analytical_methods")
    for col in ("timeout_seconds", "max_rows", "chart_contract", "result_schema_version", "execution_engine"):
        if col in cols:
            op.drop_column("analytical_methods", col)
