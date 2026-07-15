"""Add home_pins table for frozen insight snapshots and live widget pins.

Revision ID: 0052
Revises: 0051
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0052"
down_revision: str | None = "0051"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "home_pins",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column("pin_type", sa.String(length=32), nullable=False),
        sa.Column("pin_key", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("config", _JSON, nullable=False, server_default="{}"),
        sa.Column("layout", _JSON, nullable=False, server_default="{}"),
        sa.Column("frozen_payload", _JSON, nullable=True),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refresh_error", sa.String(length=1024), nullable=True),
        sa.Column(
            "is_pinned",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
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
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_home_pins_tenant_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_home_pins_user_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_home_pins_project_id",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "user_id",
            "pin_key",
            name="uix_home_pins_tenant_user_key",
        ),
    )
    op.create_index("ix_home_pins_tenant_id", "home_pins", ["tenant_id"])
    op.create_index("ix_home_pins_user_id", "home_pins", ["user_id"])
    op.create_index("ix_home_pins_project_id", "home_pins", ["project_id"])
    op.create_index("ix_home_pins_pin_type", "home_pins", ["pin_type"])


def downgrade() -> None:
    op.drop_table("home_pins")
