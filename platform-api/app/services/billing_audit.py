"""Structured audit logging for billing + provisioning.

Emits one structured log line per auditable action. Only IDs and statuses are
logged — never secret values, raw tokens, or full Stripe payloads.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger("tablescope.billing.audit")

# Canonical audit event names (Phase 14).
CHECKOUT_SESSION_CREATED = "checkout_session_created"
STRIPE_WEBHOOK_RECEIVED = "stripe_webhook_received"
STRIPE_WEBHOOK_VERIFIED = "stripe_webhook_verified"
STRIPE_EVENT_DUPLICATE_SKIPPED = "stripe_event_duplicate_skipped"
SUBSCRIPTION_SYNCED = "subscription_synced"
TENANT_PROVISIONING_STARTED = "tenant_provisioning_started"
TENANT_CREATED = "tenant_created"
SUPABASE_USER_CREATED = "supabase_user_created"
SUPABASE_EXISTING_USER_LINKED = "supabase_existing_user_linked"
TENANT_MEMBERSHIP_CREATED = "tenant_membership_created"
ROOT_ADMIN_INVITE_SENT = "root_admin_invite_sent"
SHARED_CLOUD_BOUND = "shared_cloud_bound"
ISOLATED_DATA_PLANE_STARTED = "isolated_data_plane_started"
ISOLATED_DATA_PLANE_PROVISIONED = "isolated_data_plane_provisioned"
VPN_AWS_SIDE_PROVISIONED = "vpn_aws_side_provisioned"
VPN_AWAITING_CUSTOMER_DETAILS = "vpn_awaiting_customer_details"
TENANT_PROVISIONING_FAILED = "tenant_provisioning_failed"
TENANT_PROVISIONING_COMPLETED = "tenant_provisioning_completed"
VPN_INTAKE_RECEIVED = "vpn_intake_received"


def audit(event: str, **fields: object) -> None:
    """Emit a structured audit event. Callers must pass only non-secret fields."""
    logger.info(event, audit_event=event, **fields)
