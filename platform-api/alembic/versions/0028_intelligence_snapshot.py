"""Intelligence snapshot: persist latest AI Intelligence Home run per user.

Adds:
- ``intelligence_snapshots`` — one row per user; each completed run overwrites
  it so the Home can hydrate instantly while a fresh run streams in the bg.

Revision ID: 0028
Revises: 0027
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")


def _tables(conn: sa.engine.Connection) -> set[str]:
    return set(sa.inspect(conn).get_table_names())


def upgrade() -> None:
    conn = op.get_bind()
    if "intelligence_snapshots" in _tables(conn):
        return
    op.create_table(
        "intelligence_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("granularity", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("payload", _JSON, nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_intelligence_snapshots_tenant_id",
        "intelligence_snapshots",
        ["tenant_id"],
    )
    op.create_index(
        "ix_intelligence_snapshots_user_id",
        "intelligence_snapshots",
        ["user_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("intelligence_snapshots")
