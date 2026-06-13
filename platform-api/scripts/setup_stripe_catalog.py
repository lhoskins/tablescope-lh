"""Create/update Stripe products + prices and sync the local tier catalog.

Idempotent: products are matched by the ``tablescope_tier_key`` metadata, and
recurring monthly/annual prices are reused when an active price with the same
amount/interval already exists. The ``subscription_tier_catalog`` table is
upserted with the resulting Stripe ids.

Usage:
    python -m scripts.setup_stripe_catalog [--dry-run]

Requires STRIPE_SECRET_KEY (and the platform DATABASE_URL) in the environment.
Does NOT require manual Stripe dashboard product creation.
"""

from __future__ import annotations

import argparse
import asyncio

import stripe
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.billing.tiers import TIER_DEFINITIONS, TierDefinition
from app.config import get_settings
from app.models.billing import SubscriptionTierCatalog


def _find_product(tier_key: str) -> stripe.Product | None:
    # Stripe product search by metadata (Search API).
    try:
        result = stripe.Product.search(
            query=f'metadata["tablescope_tier_key"]:"{tier_key}"', limit=1
        )
        if result.data:
            return result.data[0]
    except stripe.StripeError:
        pass
    # Fallback: scan active products.
    for product in stripe.Product.list(active=True, limit=100).auto_paging_iter():
        if product.metadata.get("tablescope_tier_key") == tier_key:
            return product
    return None


def _ensure_product(tier: TierDefinition, *, dry_run: bool) -> str:
    product = _find_product(tier.tier_key)
    if product is not None:
        if not dry_run:
            stripe.Product.modify(
                product.id,
                name=tier.display_name,
                description=tier.description,
                metadata=tier.stripe_metadata(),
            )
        print(f"  product: reuse {product.id} ({tier.display_name})")
        return str(product.id)
    if dry_run:
        print(f"  product: WOULD create ({tier.display_name})")
        return "prod_DRYRUN"
    created = stripe.Product.create(
        name=tier.display_name,
        description=tier.description,
        metadata=tier.stripe_metadata(),
    )
    print(f"  product: created {created.id} ({tier.display_name})")
    return str(created.id)


def _ensure_price(
    product_id: str, *, amount_cents: int, interval: str, tier_key: str, dry_run: bool
) -> str:
    if product_id != "prod_DRYRUN":
        for price in stripe.Price.list(product=product_id, active=True, limit=100).auto_paging_iter():
            recurring = price.recurring or {}
            if (
                price.unit_amount == amount_cents
                and price.currency == "usd"
                and recurring.get("interval") == interval
            ):
                print(f"  price ({interval}): reuse {price.id}")
                return str(price.id)
    if dry_run:
        print(f"  price ({interval}): WOULD create {amount_cents} usd")
        return f"price_DRYRUN_{interval}"
    created = stripe.Price.create(
        product=product_id,
        unit_amount=amount_cents,
        currency="usd",
        recurring={"interval": interval},
        metadata={"tablescope_tier_key": tier_key},
    )
    print(f"  price ({interval}): created {created.id}")
    return str(created.id)


async def _upsert_catalog(
    session: AsyncSession,
    tier: TierDefinition,
    *,
    product_id: str,
    monthly_price_id: str,
    annual_price_id: str,
) -> None:
    row = await session.scalar(
        select(SubscriptionTierCatalog).where(
            SubscriptionTierCatalog.tier_key == tier.tier_key
        )
    )
    if row is None:
        row = SubscriptionTierCatalog(tier_key=tier.tier_key)
        session.add(row)
    row.display_name = tier.display_name
    row.description = tier.description
    row.deployment_mode = tier.deployment_mode
    row.requires_data_plane = tier.requires_data_plane
    row.requires_vpn = tier.requires_vpn
    row.is_active = True
    row.features = {
        "highlights": tier.features,
        "monthly_price_cents": tier.monthly_price_cents,
        "annual_price_cents": tier.annual_price_cents,
    }
    row.stripe_product_id = product_id
    row.stripe_monthly_price_id = monthly_price_id
    row.stripe_annual_price_id = annual_price_id


async def run(dry_run: bool) -> None:
    settings = get_settings()
    if not settings.stripe_secret_key:
        raise SystemExit("STRIPE_SECRET_KEY is not set")
    stripe.api_key = settings.stripe_secret_key

    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        async with session.begin():
            for tier in TIER_DEFINITIONS:
                print(f"\n== {tier.tier_key} ==")
                product_id = _ensure_product(tier, dry_run=dry_run)
                monthly = _ensure_price(
                    product_id,
                    amount_cents=tier.monthly_price_cents,
                    interval="month",
                    tier_key=tier.tier_key,
                    dry_run=dry_run,
                )
                annual = _ensure_price(
                    product_id,
                    amount_cents=tier.annual_price_cents,
                    interval="year",
                    tier_key=tier.tier_key,
                    dry_run=dry_run,
                )
                if not dry_run:
                    await _upsert_catalog(
                        session,
                        tier,
                        product_id=product_id,
                        monthly_price_id=monthly,
                        annual_price_id=annual,
                    )
        if dry_run:
            print("\nDry run — no DB changes written.")
        else:
            print("\nCatalog synced to subscription_tier_catalog.")
    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Don't write to Stripe or DB.")
    args = parser.parse_args()
    asyncio.run(run(args.dry_run))


if __name__ == "__main__":
    main()
