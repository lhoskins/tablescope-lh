"""Create a checkout session (Phase 6).

Validates the tier + slug uniqueness, ensures a Stripe customer, creates a
``tenant_provisioning_request`` (status=pending_payment), and creates a Stripe
Checkout Session carrying the metadata the webhook needs to provision.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import SubscriptionTierCatalog, TenantProvisioningRequest
from app.models.tenant import Tenant
from app.schemas.billing import CheckoutSessionRequest
from app.services import billing_audit as audit
from app.services.stripe_billing_service import StripeBillingService


class CheckoutError(RuntimeError):
    pass


class SlugTakenError(CheckoutError):
    pass


class TierNotFoundError(CheckoutError):
    pass


class CheckoutService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        stripe: StripeBillingService | None = None,
    ) -> None:
        self._session = session
        self._stripe = stripe or StripeBillingService()

    async def create_checkout_session(
        self, payload: CheckoutSessionRequest
    ) -> tuple[str, int]:
        tier = await self._session.scalar(
            select(SubscriptionTierCatalog).where(
                SubscriptionTierCatalog.tier_key == payload.tier_key,
                SubscriptionTierCatalog.is_active.is_(True),
            )
        )
        if tier is None:
            raise TierNotFoundError(f"unknown tier_key {payload.tier_key!r}")

        price_id = (
            tier.stripe_annual_price_id
            if payload.billing_interval == "year"
            else tier.stripe_monthly_price_id
        )
        if not price_id:
            raise TierNotFoundError(
                f"tier {payload.tier_key!r} has no {payload.billing_interval} price configured"
            )

        # Slug uniqueness: reject only if an ACTIVE tenant already owns it, or a
        # non-terminal provisioning request is already using it. A deleted or
        # deactivated tenant frees its slug for reuse.
        existing_tenant = await self._session.scalar(
            select(Tenant).where(
                Tenant.slug == payload.tenant_slug,
                Tenant.is_active.is_(True),
            )
        )
        if existing_tenant is not None:
            raise SlugTakenError(f"tenant slug {payload.tenant_slug!r} is taken")
        existing_req = await self._session.scalar(
            select(TenantProvisioningRequest).where(
                TenantProvisioningRequest.tenant_slug == payload.tenant_slug,
                TenantProvisioningRequest.status.in_(
                    ["payment_confirmed", "provisioning", "provisioned"]
                ),
            )
        )
        if existing_req is not None:
            raise SlugTakenError(f"tenant slug {payload.tenant_slug!r} is taken")

        customer_id = await self._stripe.get_or_create_customer(
            email=payload.billing_email or payload.tenant_admin_email,
            company_name=payload.company_name,
            metadata={"tablescope_tenant_slug": payload.tenant_slug},
        )

        req = TenantProvisioningRequest(
            tier_key=tier.tier_key,
            deployment_mode=tier.deployment_mode,
            requires_data_plane=tier.requires_data_plane,
            requires_vpn=tier.requires_vpn,
            company_name=payload.company_name,
            tenant_slug=payload.tenant_slug,
            tenant_admin_email=payload.tenant_admin_email,
            tenant_admin_first_name=payload.tenant_admin_first_name,
            tenant_admin_last_name=payload.tenant_admin_last_name,
            region=payload.region,
            status="pending_payment",
            data_plane_status="not_required" if not tier.requires_data_plane else "pending",
            vpn_status="not_required" if not tier.requires_vpn else "pending",
            stripe_customer_id=customer_id,
        )
        self._session.add(req)
        await self._session.flush()

        metadata = {
            "tablescope_tier_key": tier.tier_key,
            "tenant_slug": payload.tenant_slug,
            "company_name": payload.company_name,
            "tenant_admin_email": payload.tenant_admin_email,
            "tenant_admin_first_name": payload.tenant_admin_first_name or "",
            "tenant_admin_last_name": payload.tenant_admin_last_name or "",
            "provisioning_request_id": str(req.id),
            "source": "tablescope_pricing",
        }
        session = await self._stripe.create_checkout_session(
            price_id=price_id,
            customer_id=customer_id,
            metadata=metadata,
            client_reference_id=str(req.id),
            billing_email=payload.billing_email or payload.tenant_admin_email,
        )
        req.stripe_checkout_session_id = session["id"]
        await self._session.flush()

        audit.audit(
            audit.CHECKOUT_SESSION_CREATED,
            provisioning_request_id=req.id,
            tier_key=tier.tier_key,
            tenant_slug=payload.tenant_slug,
            stripe_checkout_session_id=session["id"],
        )
        return session["url"], req.id
