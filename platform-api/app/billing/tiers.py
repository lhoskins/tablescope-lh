"""Canonical operational tier definitions.

Single source of truth for the three operational tiers, shared by the Stripe
catalog setup script and the DB catalog seed. Display tiers (Basic /
Professional / Business / Enterprise) can map onto these stable keys later.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class TierDefinition:
    tier_key: str
    display_name: str
    description: str
    deployment_mode: str
    requires_data_plane: bool
    requires_vpn: bool
    monthly_price_cents: int
    annual_price_cents: int
    features: list[str] = field(default_factory=list)

    def stripe_metadata(self) -> dict[str, str]:
        return {
            "tablescope_tier_key": self.tier_key,
            "deployment_mode": self.deployment_mode,
            "requires_data_plane": str(self.requires_data_plane).lower(),
            "requires_vpn": str(self.requires_vpn).lower(),
        }


TIER_DEFINITIONS: tuple[TierDefinition, ...] = (
    TierDefinition(
        tier_key="basic_cloud",
        display_name="Basic Cloud",
        description=(
            "Shared multi-tenant cloud deployment. Fastest onboarding for teams "
            "getting started with Tablescope."
        ),
        deployment_mode="shared_cloud",
        requires_data_plane=False,
        requires_vpn=False,
        monthly_price_cents=49900,
        annual_price_cents=499000,
        features=[
            "Shared cloud data plane",
            "AI dashboards & insights",
            "Up to standard usage limits",
            "Email support",
        ],
    ),
    TierDefinition(
        tier_key="isolated_data_plane",
        display_name="Isolated Data Plane",
        description=(
            "Dedicated, isolated VPC/data-plane infrastructure provisioned per "
            "tenant for stronger data isolation."
        ),
        deployment_mode="isolated_data_plane",
        requires_data_plane=True,
        requires_vpn=False,
        monthly_price_cents=149900,
        annual_price_cents=1499000,
        features=[
            "Dedicated isolated data plane (VPC)",
            "Tenant-scoped Teiid + storage",
            "AI dashboards & insights",
            "Priority support",
        ],
    ),
    TierDefinition(
        tier_key="isolated_data_plane_vpn",
        display_name="Isolated Data Plane + VPN",
        description=(
            "Dedicated isolated data plane plus AWS-side site-to-site VPN-ready "
            "resources to connect your on-prem network."
        ),
        deployment_mode="isolated_data_plane_vpn",
        requires_data_plane=True,
        requires_vpn=True,
        monthly_price_cents=249900,
        annual_price_cents=2499000,
        features=[
            "Everything in Isolated Data Plane",
            "AWS-side site-to-site VPN resources",
            "Connect on-prem data sources securely",
            "Dedicated onboarding",
        ],
    ),
)

TIER_BY_KEY: dict[str, TierDefinition] = {t.tier_key: t for t in TIER_DEFINITIONS}


def get_tier(tier_key: str) -> TierDefinition | None:
    return TIER_BY_KEY.get(tier_key)
