"""Tenant Allowed Domains: restrict tenant access to approved email domains.

Adds:
- ``tenants.allowed_domains_enabled`` (bool, default false) — restriction toggle.
- ``tenants.owner_user_id`` (nullable FK) — the original admin/owner, always
  exempt from the domain restriction.
- ``tenant_allowed_domains`` — one row per allowed email domain per tenant.

Revision ID: 0035
Revises: 0034
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def _inspector(conn: sa.engine.Connection) -> sa.engine.reflection.Inspector:
    return sa.inspect(conn)


def upgrade() -> None:
    conn = op.get_bind()
    insp = _inspector(conn)
    tenant_cols = {c["name"] for c in insp.get_columns("tenants")}

    if "allowed_domains_enabled" not in tenant_cols:
        op.add_column(
            "tenants",
            sa.Column(
                "allowed_domains_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
    if "owner_user_id" not in tenant_cols:
        op.add_column(
            "tenants",
            sa.Column("owner_user_id", sa.Integer(), nullable=True),
        )

    if "tenant_allowed_domains" not in set(insp.get_table_names()):
        op.create_table(
            "tenant_allowed_domains",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "tenant_id",
                sa.Integer(),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("domain", sa.String(length=255), nullable=False),
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
            sa.Column("created_by", sa.Integer(), nullable=True),
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
            "ix_tenant_allowed_domains_tenant_id",
            "tenant_allowed_domains",
            ["tenant_id"],
        )
        op.create_index(
            "uq_tenant_allowed_domain",
            "tenant_allowed_domains",
            ["tenant_id", "domain"],
            unique=True,
        )


def downgrade() -> None:
    op.drop_table("tenant_allowed_domains")
    op.drop_column("tenants", "owner_user_id")
    op.drop_column("tenants", "allowed_domains_enabled")
