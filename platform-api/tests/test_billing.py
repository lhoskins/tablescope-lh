"""Billing + Supabase/Stripe provisioning tests (Phase 15).

Covers env validation, slug validation, Stripe metadata mapping, webhook
idempotency, Supabase/local user + membership mapping, and provisioning status
transitions for all three tiers — using in-process fakes (no network).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.billing import (
    BillingEvent,
    SubscriptionTierCatalog,
    TenantProvisioningRequest,
)
from app.models.tenant import Tenant
from app.models.tenant_membership import TenantAuthBinding, TenantMembership
from app.models.user import User
from app.schemas.billing import CheckoutSessionRequest
from app.services.checkout_service import (
    CheckoutService,
    SlugTakenError,
    TierNotFoundError,
)
from app.services.stripe_webhook_handler import StripeWebhookHandler
from app.services.supabase_auth_service import SupabaseAuthService, SupabaseUser
from app.services.tenant_onboarding_service import TenantOnboardingService

# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


class FakeSupabase(SupabaseAuthService):
    """Override only the GoTrue network calls; keep real DB mapping."""

    def __init__(self, *, existing: bool = False) -> None:
        self._existing = existing
        self._counter = 0

    async def create_or_invite_user(
        self, email, *, first_name=None, last_name=None, redirect_to=None
    ) -> SupabaseUser:
        self._counter += 1
        return SupabaseUser(
            id=f"supa-{email}",
            email=email,
            created=not self._existing,
            action_link=None if self._existing else f"https://invite/{email}",
        )


class FakeEmail:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send(self, spec, *, to, template) -> bool:
        self.sent.append((to, template))
        return True


class FakeStripe:
    def __init__(self) -> None:
        self.created_sessions: list[dict] = []

    async def get_or_create_customer(self, *, email, company_name=None, metadata=None):
        return "cus_fake_123"

    async def create_checkout_session(
        self, *, price_id, customer_id, metadata, client_reference_id,
        billing_email=None, success_url=None, cancel_url=None,
    ):
        self.created_sessions.append(metadata)
        return {"id": "cs_fake_123", "url": "https://checkout.stripe/cs_fake_123"}


async def _seed_tier(
    session: AsyncSession, tier_key="basic_cloud", *, requires_data_plane=False,
    requires_vpn=False, deployment_mode="shared_cloud",
) -> SubscriptionTierCatalog:
    tier = SubscriptionTierCatalog(
        tier_key=tier_key,
        display_name=tier_key.title(),
        deployment_mode=deployment_mode,
        requires_data_plane=requires_data_plane,
        requires_vpn=requires_vpn,
        is_active=True,
        stripe_monthly_price_id="price_monthly_x",
        stripe_annual_price_id="price_annual_x",
        features={"highlights": ["a", "b"], "monthly_price_cents": 49900},
    )
    session.add(tier)
    await session.flush()
    return tier


def _onboarding(session, supabase=None, email=None) -> TenantOnboardingService:
    return TenantOnboardingService(
        session, supabase=supabase or FakeSupabase(), email=email or FakeEmail()
    )


# --------------------------------------------------------------------------- #
# Env validation
# --------------------------------------------------------------------------- #


def test_env_safety_live_mode_rejects_test_key(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("STRIPE_MODE", "live")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_abc")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("JWT_SECRET_KEY", "x" * 32)
    with pytest.raises(ValueError, match="live but a Stripe test secret key"):
        Settings()


def test_env_safety_test_mode_rejects_live_key(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("STRIPE_MODE", "test")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_abc")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("JWT_SECRET_KEY", "x" * 32)
    with pytest.raises(ValueError, match="test but a Stripe live secret key"):
        Settings()


def test_env_safety_live_mode_requires_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("STRIPE_MODE", "live")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_abc")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("JWT_SECRET_KEY", "x" * 32)
    with pytest.raises(ValueError, match="live mode in APP_ENV=staging"):
        Settings()


def test_env_safety_prod_host_allows_test_billing(monkeypatch):
    # A production app host may run billing in test mode during rollout.
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("STRIPE_MODE", "test")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_abc")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("JWT_SECRET_KEY", "x" * 32)
    assert Settings().stripe_mode == "test"


def test_resolved_project_ref_from_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("JWT_SECRET_KEY", "x" * 32)
    monkeypatch.setenv("SUPABASE_URL", "https://abcdef123.supabase.co")
    monkeypatch.delenv("SUPABASE_PROJECT_REF", raising=False)
    assert Settings().resolved_supabase_project_ref == "abcdef123"


# --------------------------------------------------------------------------- #
# Slug validation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("bad", ["has space", "under_score", "a", "dot.dot", "slash/x"])
def test_slug_validation_rejects_bad(bad):
    with pytest.raises(ValueError):
        CheckoutSessionRequest(
            tier_key="basic_cloud",
            company_name="Acme",
            tenant_name="Acme",
            tenant_slug=bad,
            tenant_admin_email="a@b.com",
        )


def test_slug_validation_normalizes_case():
    req = CheckoutSessionRequest(
        tier_key="basic_cloud",
        company_name="Acme",
        tenant_name="Acme",
        tenant_slug="Acme-Co",
        tenant_admin_email="A@B.com",
    )
    assert req.tenant_slug == "acme-co"
    assert req.tenant_admin_email == "a@b.com"


# --------------------------------------------------------------------------- #
# Checkout: metadata mapping + slug uniqueness
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_checkout_creates_request_and_metadata(db_session):
    await _seed_tier(db_session)
    fake = FakeStripe()
    svc = CheckoutService(db_session, stripe=fake)
    url, req_id = await svc.create_checkout_session(
        CheckoutSessionRequest(
            tier_key="basic_cloud",
            company_name="Acme",
            tenant_name="Acme",
            tenant_slug="acme",
            tenant_admin_email="root@acme.com",
            tenant_admin_first_name="Ann",
        )
    )
    assert url.startswith("https://checkout")
    md = fake.created_sessions[0]
    assert md["tablescope_tier_key"] == "basic_cloud"
    assert md["tenant_slug"] == "acme"
    assert md["provisioning_request_id"] == str(req_id)
    assert md["source"] == "tablescope_pricing"
    req = await db_session.get(TenantProvisioningRequest, req_id)
    assert req.status == "pending_payment"
    assert req.stripe_checkout_session_id == "cs_fake_123"


@pytest.mark.asyncio
async def test_checkout_rejects_unknown_tier(db_session):
    svc = CheckoutService(db_session, stripe=FakeStripe())
    with pytest.raises(TierNotFoundError):
        await svc.create_checkout_session(
            CheckoutSessionRequest(
                tier_key="nope", company_name="A", tenant_name="A",
                tenant_slug="acme", tenant_admin_email="a@b.com",
            )
        )


@pytest.mark.asyncio
async def test_checkout_rejects_taken_slug(db_session):
    await _seed_tier(db_session)
    db_session.add(Tenant(slug="acme", name="Acme"))
    await db_session.flush()
    svc = CheckoutService(db_session, stripe=FakeStripe())
    with pytest.raises(SlugTakenError):
        await svc.create_checkout_session(
            CheckoutSessionRequest(
                tier_key="basic_cloud", company_name="A", tenant_name="A",
                tenant_slug="acme", tenant_admin_email="a@b.com",
            )
        )


# --------------------------------------------------------------------------- #
# Provisioning transitions per tier
# --------------------------------------------------------------------------- #


async def _make_request(db_session, **overrides) -> TenantProvisioningRequest:
    defaults = dict(
        tier_key="basic_cloud",
        deployment_mode="shared_cloud",
        requires_data_plane=False,
        requires_vpn=False,
        company_name="Acme",
        tenant_slug="acme",
        tenant_admin_email="root@acme.com",
        status="payment_confirmed",
        stripe_customer_id="cus_x",
    )
    defaults.update(overrides)
    req = TenantProvisioningRequest(**defaults)
    db_session.add(req)
    await db_session.flush()
    return req


@pytest.mark.asyncio
async def test_provision_basic_cloud(db_session):
    req = await _make_request(db_session)
    email = FakeEmail()
    out = await _onboarding(db_session, email=email).provision_from_stripe_activation(req.id)
    assert out.status == "provisioned"
    assert out.data_plane_status == "shared_cloud_bound"
    assert out.vpn_status == "not_required"
    assert out.root_admin_status == "invite_sent"
    # tenant + membership created
    tenant = await db_session.scalar(select(Tenant).where(Tenant.slug == "acme"))
    assert tenant is not None
    membership = await db_session.scalar(
        select(TenantMembership).where(TenantMembership.tenant_id == tenant.id)
    )
    assert membership.role == "tenant_admin"
    binding = await db_session.scalar(select(TenantAuthBinding))
    assert binding.supabase_user_id == "supa-root@acme.com"
    assert ("root@acme.com", "root_admin_invite") in email.sent


@pytest.mark.asyncio
async def test_provision_isolated_data_plane(db_session):
    req = await _make_request(
        db_session, tier_key="isolated_data_plane",
        deployment_mode="isolated_data_plane", requires_data_plane=True,
        tenant_slug="iso",
    )
    out = await _onboarding(db_session).provision_from_stripe_activation(req.id)
    assert out.status == "provisioned"
    assert out.data_plane_status == "provisioned"
    assert out.vpn_status == "not_required"
    from app.models.tenant_data_plane import TenantDataPlane

    plane = await db_session.scalar(
        select(TenantDataPlane).where(TenantDataPlane.tenant_id == "iso")
    )
    assert plane is not None


@pytest.mark.asyncio
async def test_provision_isolated_vpn_awaits_details(db_session):
    req = await _make_request(
        db_session, tier_key="isolated_data_plane_vpn",
        deployment_mode="isolated_data_plane_vpn", requires_data_plane=True,
        requires_vpn=True, tenant_slug="vpnco",
    )
    email = FakeEmail()
    out = await _onboarding(db_session, email=email).provision_from_stripe_activation(req.id)
    assert out.status == "provisioned"
    assert out.data_plane_status == "provisioned"
    assert out.vpn_status == "awaiting_customer_network_details"
    assert any(t == "vpn_info_required" for _, t in email.sent)


@pytest.mark.asyncio
async def test_provision_is_idempotent(db_session):
    req = await _make_request(db_session)
    svc = _onboarding(db_session)
    await svc.provision_from_stripe_activation(req.id)
    # Replay: must not create duplicate tenant/membership.
    await _onboarding(db_session).provision_from_stripe_activation(req.id)
    tenants = (await db_session.scalars(select(Tenant).where(Tenant.slug == "acme"))).all()
    memberships = (await db_session.scalars(select(TenantMembership))).all()
    assert len(tenants) == 1
    assert len(memberships) == 1


@pytest.mark.asyncio
async def test_provision_links_existing_supabase_user(db_session):
    req = await _make_request(db_session)
    out = await _onboarding(
        db_session, supabase=FakeSupabase(existing=True)
    ).provision_from_stripe_activation(req.id)
    assert out.root_admin_status == "invite_sent"


# --------------------------------------------------------------------------- #
# Webhook idempotency + payment gating
# --------------------------------------------------------------------------- #


def _checkout_event(event_id="evt_1", session_id="cs_1", paid=True, req_id=None):
    return {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": session_id,
                "customer": "cus_1",
                "subscription": "sub_1",
                "payment_status": "paid" if paid else "unpaid",
                "client_reference_id": str(req_id) if req_id else None,
            }
        },
    }


@pytest.mark.asyncio
async def test_webhook_paid_provisions_tenant(db_session):
    req = await _make_request(db_session, status="pending_payment", tenant_slug="webhookco")
    handler = StripeWebhookHandler(
        db_session, onboarding=_onboarding(db_session), email=FakeEmail()
    )
    res = await handler.handle_event(
        _checkout_event(session_id=req.stripe_checkout_session_id or "cs_x", req_id=req.id)
    )
    assert res["status"] == "processed"
    await db_session.refresh(req)
    assert req.status == "provisioned"
    tenant = await db_session.scalar(select(Tenant).where(Tenant.slug == "webhookco"))
    assert tenant is not None


@pytest.mark.asyncio
async def test_webhook_duplicate_event_skipped(db_session):
    req = await _make_request(db_session, status="pending_payment", tenant_slug="dupco")
    ev = _checkout_event(event_id="evt_dup", req_id=req.id)
    handler = StripeWebhookHandler(
        db_session, onboarding=_onboarding(db_session), email=FakeEmail()
    )
    first = await handler.handle_event(ev)
    assert first["status"] == "processed"
    second = await StripeWebhookHandler(
        db_session, onboarding=_onboarding(db_session), email=FakeEmail()
    ).handle_event(ev)
    assert second["status"] == "duplicate"
    events = (await db_session.scalars(select(BillingEvent))).all()
    assert len(events) == 1
    tenants = (await db_session.scalars(select(Tenant).where(Tenant.slug == "dupco"))).all()
    assert len(tenants) == 1


@pytest.mark.asyncio
async def test_webhook_unpaid_does_not_provision(db_session):
    req = await _make_request(db_session, status="pending_payment", tenant_slug="unpaidco")
    handler = StripeWebhookHandler(
        db_session, onboarding=_onboarding(db_session), email=FakeEmail()
    )
    await handler.handle_event(
        _checkout_event(event_id="evt_unpaid", req_id=req.id, paid=False)
    )
    await db_session.refresh(req)
    assert req.status == "pending_payment"
    assert (await db_session.scalar(select(Tenant).where(Tenant.slug == "unpaidco"))) is None


# --------------------------------------------------------------------------- #
# Supabase local-user mapping (real DB path)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_link_local_user_idempotent(db_session):
    tenant = Tenant(slug="lk", name="Lk")
    db_session.add(tenant)
    await db_session.flush()
    svc = FakeSupabase()
    u1 = await svc.link_local_user(
        db_session, supabase_user_id="sub-1", email="x@y.com",
        tenant_id=tenant.id, role="root_admin",
    )
    u2 = await svc.link_local_user(
        db_session, supabase_user_id="sub-1", email="x@y.com",
        tenant_id=tenant.id, role="root_admin",
    )
    assert u1.id == u2.id
    users = (await db_session.scalars(select(User).where(User.email == "x@y.com"))).all()
    bindings = (await db_session.scalars(select(TenantAuthBinding))).all()
    assert len(users) == 1
    assert len(bindings) == 1
