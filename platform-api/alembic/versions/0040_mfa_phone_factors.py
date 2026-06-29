"""Verified SMS MFA phone factors (Twilio Verify).

Adds ``mfa_phone_factors`` — one row per user recording a verified phone for
SMS MFA. The full phone is never stored, only a masked form + salted hash.
``verified_until`` drives the aal2 elevation window.

Revision ID: 0040
Revises: 0039
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = set(sa.inspect(conn).get_table_names())
    if "mfa_phone_factors" in existing:
        return
    op.create_table(
        "mfa_phone_factors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("masked_phone", sa.String(length=32), nullable=True),
        sa.Column("phone_hash", sa.String(length=64), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_until", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", name="uq_mfa_phone_factors_user_id"),
    )
    op.create_index(
        "ix_mfa_phone_factors_tenant_id", "mfa_phone_factors", ["tenant_id"]
    )
    op.create_index("ix_mfa_phone_factors_user_id", "mfa_phone_factors", ["user_id"])
    op.create_index(
        "ix_mfa_phone_factors_phone_hash", "mfa_phone_factors", ["phone_hash"]
    )


def downgrade() -> None:
    op.drop_table("mfa_phone_factors")
