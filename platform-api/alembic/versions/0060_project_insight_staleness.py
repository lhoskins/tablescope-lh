"""Add is_stale to project_intelligence_snapshots.

Revision ID: 0060
Revises: 0059
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0060"
down_revision: str | None = "0059"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def _tables(conn: sa.engine.Connection) -> set[str]:
    return set(sa.inspect(conn).get_table_names())


def upgrade() -> None:
    conn = op.get_bind()
    tables = _tables(conn)

    if "project_intelligence_snapshots" in tables:
        inspector = sa.inspect(conn)
        cols = {c["name"] for c in inspector.get_columns("project_intelligence_snapshots")}
        if "is_stale" not in cols:
            op.add_column(
                "project_intelligence_snapshots",
                sa.Column(
                    "is_stale",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                ),
            )
        # Ensure the column is indexed for the stale-gate lookup.
        indexes = {idx["name"] for idx in inspector.get_indexes("project_intelligence_snapshots")}
        if "ix_project_intelligence_snapshots_is_stale" not in indexes:
            op.create_index(
                "ix_project_intelligence_snapshots_is_stale",
                "project_intelligence_snapshots",
                ["is_stale"],
            )


def downgrade() -> None:
    conn = op.get_bind()
    if "project_intelligence_snapshots" in _tables(conn):
        op.drop_index(
            "ix_project_intelligence_snapshots_is_stale",
            table_name="project_intelligence_snapshots",
        )
        op.drop_column("project_intelligence_snapshots", "is_stale")
