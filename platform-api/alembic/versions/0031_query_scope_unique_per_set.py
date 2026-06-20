"""Scope the query_scopes uniqueness to the parent scope set.

The old ``uq_query_scopes_full`` constraint was on
``(query_id, source_field, target_query_id, target_field)`` — global across the
whole table.  With scope sets, the *same* field mapping can legitimately live in
more than one set (e.g. an AI-generated set and a manual set), so saving a
builder map raised a UniqueViolation.  Re-key the constraint to include
``scope_set_id`` so identical mappings are allowed across different sets but
still deduped within a set.

Revision ID: 0031
Revises: 0030
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

_OLD = "uq_query_scopes_full"
_NEW = "uq_query_scopes_set_full"
_COLS = ["scope_set_id", "query_id", "source_field", "target_query_id", "target_field"]


def _has_constraint(conn: sa.engine.Connection, name: str) -> bool:
    return bool(
        conn.execute(
            sa.text("SELECT 1 FROM pg_constraint WHERE conname = :n"), {"n": name}
        ).fetchone()
    )


def upgrade() -> None:
    conn = op.get_bind()
    # Only meaningful on Postgres (named constraint via pg_constraint).
    if conn.dialect.name != "postgresql":
        return
    if _has_constraint(conn, _OLD):
        op.drop_constraint(_OLD, "query_scopes", type_="unique")
    if not _has_constraint(conn, _NEW):
        op.create_unique_constraint(_NEW, "query_scopes", _COLS)


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return
    if _has_constraint(conn, _NEW):
        op.drop_constraint(_NEW, "query_scopes", type_="unique")
    if not _has_constraint(conn, _OLD):
        op.create_unique_constraint(
            _OLD,
            "query_scopes",
            ["query_id", "source_field", "target_query_id", "target_field"],
        )
