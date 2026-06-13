"""Stripe billing integration.

Wraps the synchronous Stripe SDK for use from async FastAPI handlers (each
call runs in a worker thread). Centralises customer/checkout/webhook logic so
routes stay thin.
"""

from __future__ import annotations

import logging
from typing import Any

import stripe
from anyio import to_thread

from app.config import get_settings

logger = logging.getLogger(__name__)


class StripeConfigError(RuntimeError):
    """Raised when Stripe is not configured (secret key missing)."""


class StripeWebhookError(RuntimeError):
    """Raised when a webhook signature cannot be verified."""


class StripeBillingService:
    def __init__(self) -> None:
        settings = get_settings()
        self._secret_key = settings.stripe_secret_key
        self._webhook_secret = settings.stripe_webhook_secret
        self._success_url = settings.stripe_success_url
        self._cancel_url = settings.stripe_cancel_url

    def _require_config(self) -> None:
        if not self._secret_key:
            raise StripeConfigError("STRIPE_SECRET_KEY must be configured")
        stripe.api_key = self._secret_key

    async def get_or_create_customer(
        self,
        *,
        email: str,
        company_name: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> str:
        """Return an existing Stripe customer id for the email, or create one."""
        self._require_config()

        def _run() -> str:
            existing = stripe.Customer.list(email=email, limit=1)
            if existing.data:
                return str(existing.data[0].id)
            create_kwargs: dict[str, Any] = {"email": email, "metadata": metadata or {}}
            if company_name:
                create_kwargs["name"] = company_name
            created = stripe.Customer.create(**create_kwargs)
            return str(created.id)

        return await to_thread.run_sync(_run)

    async def create_checkout_session(
        self,
        *,
        price_id: str,
        customer_id: str,
        metadata: dict[str, str],
        client_reference_id: str,
        billing_email: str | None = None,
        success_url: str | None = None,
        cancel_url: str | None = None,
    ) -> dict[str, Any]:
        """Create a subscription Checkout Session and return {id, url}."""
        self._require_config()
        success = success_url or self._success_url
        cancel = cancel_url or self._cancel_url
        if not success or not cancel:
            raise StripeConfigError("STRIPE_SUCCESS_URL / STRIPE_CANCEL_URL must be set")

        def _run() -> dict[str, Any]:
            session = stripe.checkout.Session.create(
                mode="subscription",
                line_items=[{"price": price_id, "quantity": 1}],
                customer=customer_id,
                client_reference_id=client_reference_id,
                allow_promotion_codes=True,
                success_url=success,
                cancel_url=cancel,
                metadata=metadata,
                subscription_data={"metadata": metadata},
            )
            return {"id": session.id, "url": session.url}

        return await to_thread.run_sync(_run)

    def construct_event(self, payload: bytes, sig_header: str) -> dict[str, Any]:
        """Verify a webhook signature and return the parsed event (sync)."""
        if not self._webhook_secret:
            raise StripeConfigError("STRIPE_WEBHOOK_SECRET must be configured")
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, self._webhook_secret
            )
        except ValueError as exc:  # invalid payload
            raise StripeWebhookError(f"invalid payload: {exc}") from exc
        except stripe.SignatureVerificationError as exc:
            raise StripeWebhookError("signature verification failed") from exc
        return dict(event)

    async def retrieve_checkout_session(self, session_id: str) -> dict[str, Any]:
        self._require_config()

        def _run() -> dict[str, Any]:
            return dict(stripe.checkout.Session.retrieve(session_id))

        return await to_thread.run_sync(_run)

    async def retrieve_subscription(self, subscription_id: str) -> dict[str, Any]:
        self._require_config()

        def _run() -> dict[str, Any]:
            return dict(stripe.Subscription.retrieve(subscription_id))

        return await to_thread.run_sync(_run)
