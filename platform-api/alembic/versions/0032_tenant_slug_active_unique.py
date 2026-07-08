"""Make tenant slug reusable after deletion/deactivation.

The plain unique constraint ``tenants_slug_key`` reserved a slug forever, even
after a tenant was deleted or deactivated. Replace it with a partial unique
index that only enforces uniqueness across *active* tenants, so a freed slug can
be reused while two active tenants can never share one.

Revision ID: 0032
Revises: 0031
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

_OLD = "tenants_slug_key"
_NEW = "uq_tenants_slug_active"


def _has_constraint(conn: sa.engine.Connection, name: str) -> bool:
    return bool(
        conn.execute(
            sa.text("SELECT 1 FROM pg_constraint WHERE conname = :n"), {"n": name}
        ).fetchone()
    )


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return
    if _has_constraint(conn, _OLD):
        op.drop_constraint(_OLD, "tenants", type_="unique")
    op.execute(
        f'CREATE UNIQUE INDEX IF NOT EXISTS "{_NEW}" '
        'ON tenants (slug) WHERE is_active'
    )


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return
    op.execute(f'DROP INDEX IF EXISTS "{_NEW}"')
    if not _has_constraint(conn, _OLD):
        op.create_unique_constraint(_OLD, "tenants", ["slug"])
