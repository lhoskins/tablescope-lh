"""Add destination column to home_pins and update unique constraint.

Revision ID: 0070
Revises: 0069
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0070"
down_revision: str | None = "0069"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column(
        "home_pins",
        sa.Column(
            "destination",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'home'"),
        ),
    )
    op.create_index("ix_home_pins_destination", "home_pins", ["destination"])

    # Backfill any rows created before the server default was in effect.
    op.execute("UPDATE home_pins SET destination = 'home' WHERE destination IS NULL")

    # Same insight can now be pinned to both Home and the Insights panel.
    op.drop_constraint("uix_home_pins_tenant_user_key", "home_pins", type_="unique")
    op.create_unique_constraint(
        "uix_home_pins_tenant_user_key_destination",
        "home_pins",
        ["tenant_id", "user_id", "pin_key", "destination"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uix_home_pins_tenant_user_key_destination", "home_pins", type_="unique"
    )
    op.create_unique_constraint(
        "uix_home_pins_tenant_user_key",
        "home_pins",
        ["tenant_id", "user_id", "pin_key"],
    )
    op.drop_index("ix_home_pins_destination", table_name="home_pins")
    op.drop_column("home_pins", "destination")
