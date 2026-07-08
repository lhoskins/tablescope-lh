"""Tenant company logo columns.

Adds ``logo_url`` and ``logo_file_id`` to ``tenants`` so an admin can upload a
company/tenant logo shown in the app top header. Distinct from the static
Tablescope product logo.

Revision ID: 0044
Revises: 0043
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0044"
down_revision: str | None = "0043"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    cols = {c["name"] for c in sa.inspect(conn).get_columns("tenants")}
    if "logo_url" not in cols:
        op.add_column(
            "tenants",
            sa.Column("logo_url", sa.String(length=512), nullable=True),
        )
    if "logo_file_id" not in cols:
        op.add_column(
            "tenants",
            sa.Column("logo_file_id", sa.String(length=255), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("tenants", "logo_file_id")
    op.drop_column("tenants", "logo_url")
