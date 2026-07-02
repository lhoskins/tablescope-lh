"""Billing + provisioning models for Stripe-driven tenant onboarding.

Tenants are provisioned only after a *verified* Stripe webhook. These tables
record the Stripe catalog, customer/subscription links, raw webhook events
(for idempotency), and the provisioning request state machine.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

# JSONB on Postgres, plain JSON on other dialects (e.g. SQLite used in tests).
_JSON = JSONB().with_variant(JSON(), "sqlite")

# Stable internal tier keys (display tiers map onto these later).
TIER_KEYS = ("basic_cloud", "isolated_data_plane", "isolated_data_plane_vpn")
DEPLOYMENT_MODES = ("shared_cloud", "isolated_data_plane", "isolated_data_plane_vpn")

# tenant_provisioning_requests.status
PROVISIONING_STATUSES = (
    "pending_payment",
    "payment_confirmed",
    "provisioning",
    "provisioned",
    "failed",
    "manual_review",
    "cancelled",
    "deprovisioned",
)
DATA_PLANE_STATUSES = (
    "not_required",
    "shared_cloud_bound",
    "provisioning",
    "provisioned",
    "failed",
)
VPN_STATUSES = (
    "not_required",
    "provisioning_aws_side",
    "awaiting_customer_network_details",
    "configuring",
    "connected",
    "failed",
)
ROOT_ADMIN_STATUSES = (
    "pending",
    "supabase_user_created",
    "existing_supabase_user_linked",
    "membership_created",
    "invite_sent",
    "accepted",
    "failed",
)


class SubscriptionTierCatalog(TimestampMixin, Base):
    __tablename__ = "subscription_tier_catalog"

    id: Mapped[int] = mapped_column(primary_key=True)
    tier_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    stripe_product_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    stripe_monthly_price_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    stripe_annual_price_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    deployment_mode: Mapped[str] = mapped_column(String(64), nullable=False)
    requires_data_plane: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    requires_vpn: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    features: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict)

    def __repr__(self) -> str:
        return f"SubscriptionTierCatalog(tier_key={self.tier_key!r})"


class BillingCustomer(TimestampMixin, Base):
    __tablename__ = "billing_customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True
    )
    stripe_customer_id: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True
    )
    billing_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)

    def __repr__(self) -> str:
        return f"BillingCustomer(stripe_customer_id={self.stripe_customer_id!r})"


class BillingSubscription(TimestampMixin, Base):
    __tablename__ = "billing_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True
    )
    billing_customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("billing_customers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    stripe_subscription_id: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True
    )
    stripe_price_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    stripe_product_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tier_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    subscription_status: Mapped[str] = mapped_column(String(32), nullable=False)
    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    trial_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trial_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    def __repr__(self) -> str:
        return f"BillingSubscription(stripe_subscription_id={self.stripe_subscription_id!r})"


class BillingEvent(Base):
    """Raw Stripe webhook events, keyed by stripe_event_id for idempotency."""

    __tablename__ = "billing_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    stripe_event_id: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="received", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"BillingEvent(stripe_event_id={self.stripe_event_id!r}, status={self.status!r})"


class TenantProvisioningRequest(TimestampMixin, Base):
    __tablename__ = "tenant_provisioning_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True
    )
    billing_customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("billing_customers.id", ondelete="SET NULL"), nullable=True
    )
    billing_subscription_id: Mapped[int | None] = mapped_column(
        ForeignKey("billing_subscriptions.id", ondelete="SET NULL"), nullable=True
    )

    tier_key: Mapped[str] = mapped_column(String(64), nullable=False)
    deployment_mode: Mapped[str] = mapped_column(String(64), nullable=False)
    requires_data_plane: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    requires_vpn: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tenant_slug: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tenant_admin_email: Mapped[str] = mapped_column(String(320), nullable=False)
    tenant_admin_first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tenant_admin_last_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    region: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # State machine.
    status: Mapped[str] = mapped_column(String(32), default="pending_payment", nullable=False)
    tenant_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    billing_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    data_plane_status: Mapped[str] = mapped_column(
        String(32), default="not_required", nullable=False
    )
    vpn_status: Mapped[str] = mapped_column(String(32), default="not_required", nullable=False)
    root_admin_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)

    stripe_checkout_session_id: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True, index=True
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    provisioned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set once the single root-admin onboarding email has been sent, so replayed
    # webhooks / provisioning retries never send a duplicate.
    root_admin_email_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Optimistic-lock / row-claim counter used to make provisioning idempotent.
    lock_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (
        UniqueConstraint("stripe_checkout_session_id", name="uq_provreq_checkout_session"),
    )

    def __repr__(self) -> str:
        return (
            f"TenantProvisioningRequest(id={self.id}, tenant_slug={self.tenant_slug!r}, "
            f"status={self.status!r})"
        )
