"""Add created_at/updated_at to project_actions and project_action_subtasks.

Revision ID: 0062
Revises: 0061
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0062"
down_revision: str | None = "0061"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def _tables(conn: sa.engine.Connection) -> set[str]:
    return set(sa.inspect(conn).get_table_names())


def _has_column(conn: sa.engine.Connection, table: str, column: str) -> bool:
    cols = sa.inspect(conn).get_columns(table)
    return any(c["name"] == column for c in cols)


def upgrade() -> None:
    conn = op.get_bind()
    tables = _tables(conn)

    if "project_actions" in tables:
        if not _has_column(conn, "project_actions", "created_at"):
            op.add_column(
                "project_actions",
                sa.Column(
                    "created_at",
                    sa.DateTime(timezone=True),
                    nullable=False,
                    server_default=sa.text("now()"),
                ),
            )
        if not _has_column(conn, "project_actions", "updated_at"):
            op.add_column(
                "project_actions",
                sa.Column(
                    "updated_at",
                    sa.DateTime(timezone=True),
                    nullable=False,
                    server_default=sa.text("now()"),
                ),
            )

    if "project_action_subtasks" in tables:
        if not _has_column(conn, "project_action_subtasks", "created_at"):
            op.add_column(
                "project_action_subtasks",
                sa.Column(
                    "created_at",
                    sa.DateTime(timezone=True),
                    nullable=False,
                    server_default=sa.text("now()"),
                ),
            )
        if not _has_column(conn, "project_action_subtasks", "updated_at"):
            op.add_column(
                "project_action_subtasks",
                sa.Column(
                    "updated_at",
                    sa.DateTime(timezone=True),
                    nullable=False,
                    server_default=sa.text("now()"),
                ),
            )


def downgrade() -> None:
    conn = op.get_bind()
    tables = _tables(conn)

    if "project_action_subtasks" in tables:
        op.drop_column("project_action_subtasks", "updated_at")
        op.drop_column("project_action_subtasks", "created_at")

    if "project_actions" in tables:
        op.drop_column("project_actions", "updated_at")
        op.drop_column("project_actions", "created_at")
