"""Schemas for billing checkout, provisioning status, and VPN intake."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_LOOSE_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SLUG_RE = re.compile(r"^[a-z0-9-]+$")


class TierCard(BaseModel):
    """Public pricing-card representation of a tier."""

    model_config = ConfigDict(from_attributes=True)

    tier_key: str
    display_name: str
    description: str | None
    deployment_mode: str
    requires_data_plane: bool
    requires_vpn: bool
    monthly_price_cents: int | None = None
    annual_price_cents: int | None = None
    features: list[str] = Field(default_factory=list)
    has_monthly_price: bool = False
    has_annual_price: bool = False


class CheckoutSessionRequest(BaseModel):
    tier_key: str
    company_name: str = Field(min_length=1, max_length=255)
    tenant_name: str = Field(min_length=1, max_length=255)
    tenant_slug: str = Field(min_length=2, max_length=64)
    tenant_admin_first_name: str | None = Field(default=None, max_length=128)
    tenant_admin_last_name: str | None = Field(default=None, max_length=128)
    tenant_admin_email: str
    billing_email: str | None = None
    region: str | None = Field(default=None, max_length=64)
    billing_interval: Literal["month", "year"] = "month"
    agreed_to_terms: bool = True

    @field_validator("tenant_slug")
    @classmethod
    def _validate_slug(cls, v: str) -> str:
        v = v.strip().lower()
        if not _SLUG_RE.match(v):
            raise ValueError("tenant_slug must be lowercase alphanumeric/hyphen")
        return v

    @field_validator("tenant_admin_email", "billing_email")
    @classmethod
    def _validate_email(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not _LOOSE_EMAIL_RE.match(v):
            raise ValueError("Not a valid email address")
        return v.strip().lower()


class CheckoutSessionResponse(BaseModel):
    checkout_url: str
    provisioning_request_id: int


class ProvisioningStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str
    tenant_status: str
    billing_status: str
    data_plane_status: str
    vpn_status: str
    root_admin_status: str
    tenant_slug: str
    company_name: str | None = None
    tier_key: str
    requires_vpn: bool
    error_message: str | None = None


class VpnIntakeRequest(BaseModel):
    public_endpoint: str = Field(min_length=1, max_length=255)
    customer_cidr_ranges: list[str] = Field(min_length=1)
    gateway_vendor: str | None = Field(default=None, max_length=128)
    ike_version: Literal["ikev1", "ikev2"] = "ikev2"
    routing: Literal["bgp", "static"] = "static"
    technical_contact: str | None = Field(default=None, max_length=255)
    maintenance_window: str | None = Field(default=None, max_length=255)


class VpnIntakeResponse(BaseModel):
    vpn_status: str
    message: str
