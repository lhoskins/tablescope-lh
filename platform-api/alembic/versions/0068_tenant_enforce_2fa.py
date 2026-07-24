"""Add tenant enforce_2fa flag.

Revision ID: 0068
Revises: 0067
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0068"
down_revision: str | None = "0067"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "enforce_2fa",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("tenants", "enforce_2fa")
