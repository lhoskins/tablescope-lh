"""Supabase auth + Stripe billing: memberships, auth bindings, billing tables.

Revision ID: 0022
Revises: 0021
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

_TS = dict(server_default=sa.func.now(), nullable=False)


def _has_table(conn: sa.engine.Connection, table: str) -> bool:
    return sa.inspect(conn).has_table(table)


def _has_column(conn: sa.engine.Connection, table: str, column: str) -> bool:
    insp = sa.inspect(conn)
    if not insp.has_table(table):
        return False
    return any(c["name"] == column for c in insp.get_columns(table))


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("updated_at", sa.DateTime(timezone=True), **_TS),
    ]


def upgrade() -> None:
    conn = op.get_bind()

    # --- users: extra profile/identity columns ---
    for col, type_ in (
        ("supabase_user_id", sa.String(length=255)),
        ("first_name", sa.String(length=128)),
        ("last_name", sa.String(length=128)),
    ):
        if not _has_column(conn, "users", col):
            op.add_column("users", sa.Column(col, type_, nullable=True))
    if not _has_column(conn, "users", "status"):
        op.add_column(
            "users",
            sa.Column(
                "status", sa.String(length=32), nullable=False, server_default="active"
            ),
        )
    if _has_column(conn, "users", "supabase_user_id"):
        op.create_index(
            "ix_users_supabase_user_id", "users", ["supabase_user_id"], unique=False
        )

    # --- tenant_memberships ---
    if not _has_table(conn, "tenant_memberships"):
        op.create_table(
            "tenant_memberships",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column(
                "tenant_id",
                sa.Integer,
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                sa.Integer,
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("role", sa.String(length=32), nullable=False, server_default="viewer"),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
            *_timestamps(),
            sa.UniqueConstraint(
                "tenant_id", "user_id", name="uq_tenant_membership_tenant_user"
            ),
        )
        op.create_index(
            "ix_tenant_memberships_tenant_id", "tenant_memberships", ["tenant_id"]
        )
        op.create_index(
            "ix_tenant_memberships_user_id", "tenant_memberships", ["user_id"]
        )

    # --- tenant_auth_bindings ---
    if not _has_table(conn, "tenant_auth_bindings"):
        op.create_table(
            "tenant_auth_bindings",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column(
                "tenant_id",
                sa.Integer,
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column(
                "user_id",
                sa.Integer,
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "provider", sa.String(length=32), nullable=False, server_default="supabase"
            ),
            sa.Column("supabase_user_id", sa.String(length=255), nullable=False),
            sa.Column("email", sa.String(length=320), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
            *_timestamps(),
            sa.UniqueConstraint(
                "provider", "supabase_user_id", name="uq_auth_binding_provider_subject"
            ),
        )
        op.create_index(
            "ix_tenant_auth_bindings_supabase_user_id",
            "tenant_auth_bindings",
            ["supabase_user_id"],
        )
        op.create_index(
            "ix_tenant_auth_bindings_tenant_id", "tenant_auth_bindings", ["tenant_id"]
        )
        op.create_index(
            "ix_tenant_auth_bindings_email", "tenant_auth_bindings", ["email"]
        )

    # --- subscription_tier_catalog ---
    if not _has_table(conn, "subscription_tier_catalog"):
        op.create_table(
            "subscription_tier_catalog",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("tier_key", sa.String(length=64), nullable=False),
            sa.Column("display_name", sa.String(length=128), nullable=False),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("stripe_product_id", sa.String(length=128), nullable=True),
            sa.Column("stripe_monthly_price_id", sa.String(length=128), nullable=True),
            sa.Column("stripe_annual_price_id", sa.String(length=128), nullable=True),
            sa.Column("deployment_mode", sa.String(length=64), nullable=False),
            sa.Column(
                "requires_data_plane", sa.Boolean, nullable=False, server_default=sa.false()
            ),
            sa.Column("requires_vpn", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("features", sa.JSON, nullable=False, server_default="{}"),
            *_timestamps(),
            sa.UniqueConstraint("tier_key", name="uq_tier_catalog_tier_key"),
        )

    # --- billing_customers ---
    if not _has_table(conn, "billing_customers"):
        op.create_table(
            "billing_customers",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column(
                "tenant_id",
                sa.Integer,
                sa.ForeignKey("tenants.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("stripe_customer_id", sa.String(length=128), nullable=False),
            sa.Column("billing_email", sa.String(length=320), nullable=True),
            sa.Column("company_name", sa.String(length=255), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
            *_timestamps(),
            sa.UniqueConstraint(
                "stripe_customer_id", name="uq_billing_customer_stripe_id"
            ),
        )
        op.create_index(
            "ix_billing_customers_tenant_id", "billing_customers", ["tenant_id"]
        )

    # --- billing_subscriptions ---
    if not _has_table(conn, "billing_subscriptions"):
        op.create_table(
            "billing_subscriptions",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column(
                "tenant_id",
                sa.Integer,
                sa.ForeignKey("tenants.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "billing_customer_id",
                sa.Integer,
                sa.ForeignKey("billing_customers.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("stripe_subscription_id", sa.String(length=128), nullable=False),
            sa.Column("stripe_price_id", sa.String(length=128), nullable=True),
            sa.Column("stripe_product_id", sa.String(length=128), nullable=True),
            sa.Column("tier_key", sa.String(length=64), nullable=True),
            sa.Column("subscription_status", sa.String(length=32), nullable=False),
            sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
            sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
            sa.Column("trial_start", sa.DateTime(timezone=True), nullable=True),
            sa.Column("trial_end", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "cancel_at_period_end", sa.Boolean, nullable=False, server_default=sa.false()
            ),
            *_timestamps(),
            sa.UniqueConstraint(
                "stripe_subscription_id", name="uq_billing_sub_stripe_id"
            ),
        )
        op.create_index(
            "ix_billing_subscriptions_tenant_id", "billing_subscriptions", ["tenant_id"]
        )

    # --- billing_events (webhook idempotency) ---
    if not _has_table(conn, "billing_events"):
        op.create_table(
            "billing_events",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("stripe_event_id", sa.String(length=128), nullable=False),
            sa.Column("event_type", sa.String(length=128), nullable=False),
            sa.Column("payload", sa.JSON, nullable=False, server_default="{}"),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="received"),
            sa.Column("error_message", sa.Text, nullable=True),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), **_TS),
            sa.UniqueConstraint("stripe_event_id", name="uq_billing_event_stripe_id"),
        )

    # --- tenant_provisioning_requests ---
    if not _has_table(conn, "tenant_provisioning_requests"):
        op.create_table(
            "tenant_provisioning_requests",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column(
                "tenant_id",
                sa.Integer,
                sa.ForeignKey("tenants.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "billing_customer_id",
                sa.Integer,
                sa.ForeignKey("billing_customers.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "billing_subscription_id",
                sa.Integer,
                sa.ForeignKey("billing_subscriptions.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("tier_key", sa.String(length=64), nullable=False),
            sa.Column("deployment_mode", sa.String(length=64), nullable=False),
            sa.Column(
                "requires_data_plane", sa.Boolean, nullable=False, server_default=sa.false()
            ),
            sa.Column("requires_vpn", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("company_name", sa.String(length=255), nullable=True),
            sa.Column("tenant_slug", sa.String(length=64), nullable=False),
            sa.Column("tenant_admin_email", sa.String(length=320), nullable=False),
            sa.Column("tenant_admin_first_name", sa.String(length=128), nullable=True),
            sa.Column("tenant_admin_last_name", sa.String(length=128), nullable=True),
            sa.Column("region", sa.String(length=64), nullable=True),
            sa.Column(
                "status", sa.String(length=32), nullable=False, server_default="pending_payment"
            ),
            sa.Column(
                "tenant_status", sa.String(length=32), nullable=False, server_default="pending"
            ),
            sa.Column(
                "billing_status", sa.String(length=32), nullable=False, server_default="pending"
            ),
            sa.Column(
                "data_plane_status",
                sa.String(length=32),
                nullable=False,
                server_default="not_required",
            ),
            sa.Column(
                "vpn_status", sa.String(length=32), nullable=False, server_default="not_required"
            ),
            sa.Column(
                "root_admin_status",
                sa.String(length=32),
                nullable=False,
                server_default="pending",
            ),
            sa.Column("stripe_checkout_session_id", sa.String(length=255), nullable=True),
            sa.Column("stripe_customer_id", sa.String(length=128), nullable=True),
            sa.Column("stripe_subscription_id", sa.String(length=128), nullable=True),
            sa.Column("error_message", sa.Text, nullable=True),
            sa.Column("provisioned_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("lock_version", sa.Integer, nullable=False, server_default="0"),
            *_timestamps(),
            sa.UniqueConstraint(
                "stripe_checkout_session_id", name="uq_provreq_checkout_session"
            ),
        )
        op.create_index(
            "ix_provreq_tenant_id", "tenant_provisioning_requests", ["tenant_id"]
        )
        op.create_index(
            "ix_provreq_tenant_slug", "tenant_provisioning_requests", ["tenant_slug"]
        )
        op.create_index(
            "ix_provreq_checkout_session",
            "tenant_provisioning_requests",
            ["stripe_checkout_session_id"],
        )


def downgrade() -> None:
    conn = op.get_bind()
    for table in (
        "tenant_provisioning_requests",
        "billing_events",
        "billing_subscriptions",
        "billing_customers",
        "subscription_tier_catalog",
        "tenant_auth_bindings",
        "tenant_memberships",
    ):
        if _has_table(conn, table):
            op.drop_table(table)
    if _has_column(conn, "users", "supabase_user_id"):
        op.drop_index("ix_users_supabase_user_id", table_name="users")
    for col in ("status", "last_name", "first_name", "supabase_user_id"):
        if _has_column(conn, "users", col):
            op.drop_column("users", col)
