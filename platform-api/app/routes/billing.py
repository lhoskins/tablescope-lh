"""Public billing routes: pricing catalog, checkout session, Stripe webhook."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.billing import SubscriptionTierCatalog
from app.schemas.billing import (
    CheckoutSessionRequest,
    CheckoutSessionResponse,
    TenantSlugAvailabilityResponse,
    TierCard,
)
from app.services import billing_audit as audit
from app.services.checkout_service import (
    CheckoutService,
    SlugTakenError,
    TierNotFoundError,
)
from app.services.stripe_billing_service import (
    StripeBillingService,
    StripeConfigError,
    StripeWebhookError,
)
from app.services.stripe_webhook_handler import StripeWebhookHandler

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/billing", tags=["billing"])


def _to_card(tier: SubscriptionTierCatalog) -> TierCard:
    features = tier.features or {}
    return TierCard(
        tier_key=tier.tier_key,
        display_name=tier.display_name,
        description=tier.description,
        deployment_mode=tier.deployment_mode,
        requires_data_plane=tier.requires_data_plane,
        requires_vpn=tier.requires_vpn,
        monthly_price_cents=features.get("monthly_price_cents"),
        annual_price_cents=features.get("annual_price_cents"),
        features=features.get("highlights", []),
        has_monthly_price=bool(tier.stripe_monthly_price_id),
        has_annual_price=bool(tier.stripe_annual_price_id),
    )


@router.get("/catalog", response_model=list[TierCard])
async def get_catalog(session: AsyncSession = Depends(get_db)) -> list[TierCard]:
    rows = (
        await session.scalars(
            select(SubscriptionTierCatalog)
            .where(SubscriptionTierCatalog.is_active.is_(True))
            .order_by(SubscriptionTierCatalog.id)
        )
    ).all()
    return [_to_card(r) for r in rows]


@router.get(
    "/tenant-slug-availability",
    response_model=TenantSlugAvailabilityResponse,
)
async def tenant_slug_availability(
    slug: str = Query(..., min_length=1, max_length=64),
    session: AsyncSession = Depends(get_db),
) -> TenantSlugAvailabilityResponse:
    """Public check for whether a workspace slug is available to claim."""
    normalized = slug.strip().lower()
    available, reason = await CheckoutService(session).check_slug_availability(
        normalized
    )
    return TenantSlugAvailabilityResponse(
        slug=normalized, available=available, reason=reason
    )


@router.post("/checkout/session", response_model=CheckoutSessionResponse)
async def create_checkout_session(
    payload: CheckoutSessionRequest,
    session: AsyncSession = Depends(get_db),
) -> CheckoutSessionResponse:
    service = CheckoutService(session)
    try:
        url, request_id = await service.create_checkout_session(payload)
    except SlugTakenError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except TierNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except StripeConfigError as exc:
        logger.error("Stripe not configured for checkout: %s", exc)
        raise HTTPException(status_code=503, detail="Billing is not configured") from exc
    return CheckoutSessionResponse(checkout_url=url, provisioning_request_id=request_id)


@router.post("/stripe/webhook")
async def stripe_webhook(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    audit.audit(audit.STRIPE_WEBHOOK_RECEIVED, has_signature=bool(sig))

    stripe_service = StripeBillingService()
    try:
        event = stripe_service.construct_event(payload, sig)
    except StripeWebhookError as exc:
        logger.warning("Rejected Stripe webhook: %s", exc)
        raise HTTPException(status_code=400, detail="invalid signature") from exc
    except StripeConfigError as exc:
        logger.error("Stripe webhook secret not configured: %s", exc)
        raise HTTPException(status_code=503, detail="Webhook not configured") from exc

    handler = StripeWebhookHandler(session)
    result = await handler.handle_event(event)
    return result
