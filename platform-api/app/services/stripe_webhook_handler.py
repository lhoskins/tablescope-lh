"""Process verified Stripe webhook events (Phase 7 + Phase 12 lifecycle).

Idempotent: every event is recorded in ``billing_events`` keyed by
``stripe_event_id``; duplicates are skipped. Tenant provisioning is only
started after a confirmed paid/trialing/no-payment-required event.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import (
    BillingCustomer,
    BillingEvent,
    BillingSubscription,
    TenantProvisioningRequest,
)
from app.models.tenant import Tenant
from app.services import billing_audit as audit
from app.services.email_service import (
    EmailService,
    render_payment_failed,
    render_subscription_cancelled,
)
from app.services.tenant_onboarding_service import TenantOnboardingService

_PAID_STATUSES = {"paid", "no_payment_required"}
_ACTIVE_SUB_STATUSES = {"active", "trialing"}


def _ts(value: Any) -> datetime | None:
    if value in (None, 0):
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def _obj_id(value: Any) -> str | None:
    """Stripe fields may be a bare id or an expanded object."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("id")
    return getattr(value, "id", None)


class StripeWebhookHandler:
    def __init__(
        self,
        session: AsyncSession,
        *,
        onboarding: TenantOnboardingService | None = None,
        email: EmailService | None = None,
    ) -> None:
        self._session = session
        self._onboarding = onboarding or TenantOnboardingService(session)
        self._email = email or EmailService()

    async def handle_event(self, event: dict[str, Any]) -> dict[str, str]:
        event_id = event.get("id", "")
        event_type = event.get("type", "")
        audit.audit(
            audit.STRIPE_WEBHOOK_VERIFIED, stripe_event_id=event_id, event_type=event_type
        )

        # Idempotency gate: record the event id first.
        record = BillingEvent(
            stripe_event_id=event_id,
            event_type=event_type,
            payload={"id": event_id, "type": event_type},
            status="received",
        )
        self._session.add(record)
        try:
            await self._session.flush()
        except IntegrityError:
            await self._session.rollback()
            audit.audit(
                audit.STRIPE_EVENT_DUPLICATE_SKIPPED, stripe_event_id=event_id
            )
            return {"status": "duplicate"}

        obj = event.get("data", {}).get("object", {})
        try:
            if event_type == "checkout.session.completed":
                await self._on_checkout_completed(obj)
            elif event_type in ("customer.subscription.created", "customer.subscription.updated"):
                await self._on_subscription_upsert(obj)
            elif event_type == "customer.subscription.deleted":
                await self._on_subscription_deleted(obj)
            elif event_type == "invoice.paid":
                await self._on_invoice_paid(obj)
            elif event_type == "invoice.payment_failed":
                await self._on_invoice_payment_failed(obj)
            record.status = "processed"
            record.processed_at = datetime.now(UTC)
        except Exception as exc:
            record.status = "error"
            record.error_message = str(exc)[:500]
            await self._session.flush()
            raise
        await self._session.flush()
        return {"status": "processed"}

    # --- handlers ----------------------------------------------------------------

    async def _find_request(
        self, *, session_id: str | None = None, subscription_id: str | None = None
    ) -> TenantProvisioningRequest | None:
        if session_id:
            req = await self._session.scalar(
                select(TenantProvisioningRequest).where(
                    TenantProvisioningRequest.stripe_checkout_session_id == session_id
                )
            )
            if req is not None:
                return req
        if subscription_id:
            return await self._session.scalar(
                select(TenantProvisioningRequest).where(
                    TenantProvisioningRequest.stripe_subscription_id == subscription_id
                )
            )
        return None

    async def _on_checkout_completed(self, obj: dict[str, Any]) -> None:
        session_id = obj.get("id")
        customer_id = _obj_id(obj.get("customer"))
        subscription_id = _obj_id(obj.get("subscription"))
        payment_status = obj.get("payment_status")
        req = await self._find_request(session_id=session_id)
        if req is None:
            ref = obj.get("client_reference_id")
            if ref and ref.isdigit():
                req = await self._session.get(TenantProvisioningRequest, int(ref))
        if req is None:
            return

        if customer_id:
            req.stripe_customer_id = customer_id
            await self._ensure_billing_customer(customer_id, req)
        if subscription_id:
            req.stripe_subscription_id = subscription_id

        if payment_status in _PAID_STATUSES:
            req.status = "payment_confirmed"
            req.billing_status = "active"
            await self._session.flush()
            await self._onboarding.provision_from_stripe_activation(req.id)
        else:
            req.status = "pending_payment"
            await self._session.flush()

    async def _on_subscription_upsert(self, obj: dict[str, Any]) -> None:
        sub = await self._sync_subscription(obj)
        audit.audit(
            audit.SUBSCRIPTION_SYNCED,
            stripe_subscription_id=sub.stripe_subscription_id,
            subscription_status=sub.subscription_status,
        )
        if sub.subscription_status in _ACTIVE_SUB_STATUSES:
            req = await self._find_request(subscription_id=sub.stripe_subscription_id)
            if req is None:
                req = await self._link_request_to_subscription(obj, sub)
            if req is not None and req.status in (
                "pending_payment",
                "payment_confirmed",
                "provisioning",
                "failed",
            ):
                req.status = "payment_confirmed"
                req.billing_status = "active"
                await self._session.flush()
                await self._onboarding.provision_from_stripe_activation(req.id)

    async def _on_subscription_deleted(self, obj: dict[str, Any]) -> None:
        sub = await self._sync_subscription(obj)
        sub.subscription_status = "canceled"
        sub.cancel_at_period_end = True
        req = await self._find_request(subscription_id=sub.stripe_subscription_id)
        if req is not None:
            req.billing_status = "cancelled"
            req.tenant_status = "suspended"
        if sub.tenant_id is not None:
            tenant = await self._session.get(Tenant, sub.tenant_id)
            if tenant is not None:
                tenant.is_active = False  # suspend, do NOT delete
                recipient = await self._recipient_email(req, sub)
                if recipient:
                    await self._email.send(
                        render_subscription_cancelled(company_name=tenant.name),
                        to=recipient,
                        template="subscription_cancelled",
                    )
        await self._session.flush()

    async def _on_invoice_paid(self, obj: dict[str, Any]) -> None:
        subscription_id = _obj_id(obj.get("subscription"))
        req = await self._find_request(subscription_id=subscription_id)
        if req is not None and req.status in ("pending_payment", "failed"):
            req.status = "payment_confirmed"
            req.billing_status = "active"
            await self._session.flush()
            await self._onboarding.provision_from_stripe_activation(req.id)

    async def _on_invoice_payment_failed(self, obj: dict[str, Any]) -> None:
        subscription_id = _obj_id(obj.get("subscription"))
        sub = await self._session.scalar(
            select(BillingSubscription).where(
                BillingSubscription.stripe_subscription_id == subscription_id
            )
        )
        if sub is None:
            return
        req = await self._find_request(subscription_id=subscription_id)
        if req is not None:
            req.billing_status = "past_due"
        if sub.tenant_id is not None:
            tenant = await self._session.get(Tenant, sub.tenant_id)
            if tenant is not None:
                recipient = await self._recipient_email(req, sub)
                if recipient:
                    await self._email.send(
                        render_payment_failed(company_name=tenant.name),
                        to=recipient,
                        template="payment_failed",
                    )
        await self._session.flush()

    # --- helpers -----------------------------------------------------------------

    async def _ensure_billing_customer(
        self, customer_id: str, req: TenantProvisioningRequest
    ) -> BillingCustomer:
        customer = await self._session.scalar(
            select(BillingCustomer).where(
                BillingCustomer.stripe_customer_id == customer_id
            )
        )
        if customer is None:
            customer = BillingCustomer(
                stripe_customer_id=customer_id,
                billing_email=req.tenant_admin_email,
                company_name=req.company_name,
            )
            self._session.add(customer)
            await self._session.flush()
        req.billing_customer_id = customer.id
        return customer

    async def _sync_subscription(self, obj: dict[str, Any]) -> BillingSubscription:
        sub_id = obj.get("id")
        sub = await self._session.scalar(
            select(BillingSubscription).where(
                BillingSubscription.stripe_subscription_id == sub_id
            )
        )
        if sub is None:
            sub = BillingSubscription(
                stripe_subscription_id=sub_id, subscription_status=obj.get("status", "incomplete")
            )
            self._session.add(sub)

        items = (obj.get("items", {}) or {}).get("data", [])
        price = items[0].get("price", {}) if items else {}
        sub.subscription_status = obj.get("status", sub.subscription_status)
        sub.stripe_price_id = price.get("id") or sub.stripe_price_id
        sub.stripe_product_id = _obj_id(price.get("product")) or sub.stripe_product_id
        tier_key = (obj.get("metadata", {}) or {}).get("tablescope_tier_key")
        if tier_key:
            sub.tier_key = tier_key
        sub.current_period_start = _ts(obj.get("current_period_start"))
        sub.current_period_end = _ts(obj.get("current_period_end"))
        sub.trial_start = _ts(obj.get("trial_start"))
        sub.trial_end = _ts(obj.get("trial_end"))
        sub.cancel_at_period_end = bool(obj.get("cancel_at_period_end", False))

        customer_id = _obj_id(obj.get("customer"))
        if customer_id:
            customer = await self._session.scalar(
                select(BillingCustomer).where(
                    BillingCustomer.stripe_customer_id == customer_id
                )
            )
            if customer is not None:
                sub.billing_customer_id = customer.id
                if customer.tenant_id is not None:
                    sub.tenant_id = customer.tenant_id
        await self._session.flush()
        return sub

    async def _link_request_to_subscription(
        self, obj: dict[str, Any], sub: BillingSubscription
    ) -> TenantProvisioningRequest | None:
        """Attach a subscription to a provisioning request via shared customer."""
        customer_id = _obj_id(obj.get("customer"))
        if not customer_id:
            return None
        req = await self._session.scalar(
            select(TenantProvisioningRequest).where(
                TenantProvisioningRequest.stripe_customer_id == customer_id,
                TenantProvisioningRequest.status.in_(
                    ["pending_payment", "payment_confirmed", "provisioning", "failed"]
                ),
            )
        )
        if req is not None:
            req.stripe_subscription_id = sub.stripe_subscription_id
            req.billing_subscription_id = sub.id
            await self._session.flush()
        return req

    async def _recipient_email(
        self,
        req: TenantProvisioningRequest | None,
        sub: BillingSubscription,
    ) -> str | None:
        if req is not None and req.tenant_admin_email:
            return req.tenant_admin_email
        if sub.billing_customer_id is not None:
            customer = await self._session.get(BillingCustomer, sub.billing_customer_id)
            if customer is not None:
                return customer.billing_email
        return None



