"""Query/dashboard workspace metadata for the Concept A UI.

Adds lightweight presentation/usage metadata used by the project workspace
screens (Queries, Dashboards):

* ``saved_queries``: ``ai_generated``, ``is_shared``, ``run_count``,
  ``last_run_at``, ``avg_runtime_ms``
* ``dashboards``: ``ai_generated``, ``view_count``

All columns are nullable or carry a server default so the migration is safe to
apply to existing rows.

Revision ID: 0024
Revises: 0023
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def _columns(conn: sa.engine.Connection, table: str) -> set[str]:
    insp = sa.inspect(conn)
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    conn = op.get_bind()

    sq_cols = _columns(conn, "saved_queries")
    if "ai_generated" not in sq_cols:
        op.add_column(
            "saved_queries",
            sa.Column(
                "ai_generated",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
    if "is_shared" not in sq_cols:
        op.add_column(
            "saved_queries",
            sa.Column(
                "is_shared",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
    if "run_count" not in sq_cols:
        op.add_column(
            "saved_queries",
            sa.Column(
                "run_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )
    if "last_run_at" not in sq_cols:
        op.add_column(
            "saved_queries",
            sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "avg_runtime_ms" not in sq_cols:
        op.add_column(
            "saved_queries",
            sa.Column("avg_runtime_ms", sa.Integer(), nullable=True),
        )

    dash_cols = _columns(conn, "dashboards")
    if "ai_generated" not in dash_cols:
        op.add_column(
            "dashboards",
            sa.Column(
                "ai_generated",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
    if "view_count" not in dash_cols:
        op.add_column(
            "dashboards",
            sa.Column(
                "view_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )


def downgrade() -> None:
    for col in ("avg_runtime_ms", "last_run_at", "run_count", "is_shared", "ai_generated"):
        op.drop_column("saved_queries", col)
    for col in ("view_count", "ai_generated"):
        op.drop_column("dashboards", col)
