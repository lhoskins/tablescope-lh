"""Twilio SMS MFA audit + usage tracking table.

Adds ``mfa_sms_events`` for tenant-level SMS MFA tracking (cost control,
rate limiting, and audit). The full phone number is never stored — only a
masked display form and a salted hash.

Revision ID: 0039
Revises: 0038
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = set(sa.inspect(conn).get_table_names())
    if "mfa_sms_events" in existing:
        return
    op.create_table(
        "mfa_sms_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("masked_phone", sa.String(length=32), nullable=True),
        sa.Column("phone_hash", sa.String(length=64), nullable=True),
        sa.Column("twilio_message_sid", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_mfa_sms_events_tenant_id", "mfa_sms_events", ["tenant_id"]
    )
    op.create_index("ix_mfa_sms_events_user_id", "mfa_sms_events", ["user_id"])
    op.create_index(
        "ix_mfa_sms_events_phone_hash", "mfa_sms_events", ["phone_hash"]
    )
    op.create_index(
        "ix_mfa_sms_events_phone_created",
        "mfa_sms_events",
        ["phone_hash", "created_at"],
    )
    op.create_index(
        "ix_mfa_sms_events_user_created",
        "mfa_sms_events",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("mfa_sms_events")
