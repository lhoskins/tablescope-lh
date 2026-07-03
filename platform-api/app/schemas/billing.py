"""Schemas for billing checkout, provisioning status, and VPN intake."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    # Optional: defaults to company_name when omitted (the form no longer asks
    # for a separate workspace name).
    tenant_name: str | None = Field(default=None, max_length=255)
    tenant_slug: str = Field(min_length=2, max_length=64)
    tenant_admin_first_name: str | None = Field(default=None, max_length=128)
    tenant_admin_last_name: str | None = Field(default=None, max_length=128)
    tenant_admin_email: str
    # Must equal tenant_admin_email (case-insensitive). Optional for API
    # backward-compat; when present it is enforced.
    confirm_admin_email: str | None = None
    tenant_admin_phone: str | None = Field(default=None, max_length=32)
    billing_email: str | None = None
    company_street: str | None = Field(default=None, max_length=255)
    company_city: str | None = Field(default=None, max_length=128)
    company_state: str | None = Field(default=None, max_length=128)
    company_postal_code: str | None = Field(default=None, max_length=32)
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

    @field_validator(
        "tenant_admin_email", "billing_email", "confirm_admin_email"
    )
    @classmethod
    def _validate_email(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not _LOOSE_EMAIL_RE.match(v):
            raise ValueError("Not a valid email address")
        return v.strip().lower()

    @model_validator(mode="after")
    def _emails_match_and_defaults(self) -> CheckoutSessionRequest:
        # Confirm-email must match the admin email (both already normalized to
        # lowercase/trimmed by the field validator).
        if (
            self.confirm_admin_email is not None
            and self.confirm_admin_email != self.tenant_admin_email
        ):
            raise ValueError("Admin email and confirmation email must match")
        if not self.tenant_name:
            self.tenant_name = self.company_name
        return self


class CheckoutSessionResponse(BaseModel):
    checkout_url: str
    provisioning_request_id: int


class TenantSlugAvailabilityResponse(BaseModel):
    slug: str
    available: bool
    reason: str | None = None


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
