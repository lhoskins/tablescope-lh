"""Tenant provisioning: idempotent root-admin email marker.

Adds ``root_admin_email_sent_at`` to ``tenant_provisioning_requests`` so the
single onboarding email is sent exactly once even when a Stripe webhook is
replayed or provisioning is retried after a failure.

Revision ID: 0041
Revises: 0040
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    cols = {
        c["name"]
        for c in sa.inspect(conn).get_columns("tenant_provisioning_requests")
    }
    if "root_admin_email_sent_at" not in cols:
        op.add_column(
            "tenant_provisioning_requests",
            sa.Column(
                "root_admin_email_sent_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )


def downgrade() -> None:
    op.drop_column(
        "tenant_provisioning_requests", "root_admin_email_sent_at"
    )
