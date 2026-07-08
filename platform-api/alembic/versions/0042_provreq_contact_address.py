"""Tenant provisioning: admin phone + company address fields.

Adds ``tenant_admin_phone`` and the company mailing-address columns
(``company_street``/``company_city``/``company_state``/``company_postal_code``)
to ``tenant_provisioning_requests`` so the provisioning form can capture them.

Revision ID: 0042
Revises: 0041
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


_NEW_COLUMNS = (
    ("tenant_admin_phone", sa.String(length=32)),
    ("company_street", sa.String(length=255)),
    ("company_city", sa.String(length=128)),
    ("company_state", sa.String(length=128)),
    ("company_postal_code", sa.String(length=32)),
)


def upgrade() -> None:
    conn = op.get_bind()
    cols = {
        c["name"]
        for c in sa.inspect(conn).get_columns("tenant_provisioning_requests")
    }
    for name, col_type in _NEW_COLUMNS:
        if name not in cols:
            op.add_column(
                "tenant_provisioning_requests",
                sa.Column(name, col_type, nullable=True),
            )


def downgrade() -> None:
    for name, _ in reversed(_NEW_COLUMNS):
        op.drop_column("tenant_provisioning_requests", name)
