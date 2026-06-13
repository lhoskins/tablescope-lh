"""Verified-webhook-gated tenant onboarding orchestration (Phase 8).

`provision_from_stripe_activation` is invoked only after a Stripe webhook
confirms payment. It is idempotent: replayed webhooks never create duplicate
tenants, users, memberships, or data planes.

Tier behaviour:
  * basic_cloud             -> bind to shared cloud data plane (no infra)
  * isolated_data_plane     -> provision dedicated VPC/data-plane (real automation)
  * isolated_data_plane_vpn -> provision data-plane + AWS-side VPN-ready resources,
                               then await customer network details (collected post-login)
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import (
    BillingCustomer,
    BillingSubscription,
    TenantProvisioningRequest,
)
from app.models.project import Project
from app.models.tenant import Tenant
from app.models.tenant_membership import TenantMembership
from app.models.user import User
from app.services import billing_audit as audit
from app.services.email_service import (
    EmailService,
    render_root_admin_invite,
    render_tenant_ready,
    render_vpn_info_required,
)
from app.services.supabase_auth_service import SupabaseAuthService
from app.services.tenant_provisioning_service import (
    TenantAlreadyExists,
    TenantProvisioningService,
)


class OnboardingError(RuntimeError):
    pass


# Statuses from which provisioning may (re)start.
_PROVISIONABLE = {"payment_confirmed", "provisioning", "failed", "manual_review"}


class TenantOnboardingService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        supabase: SupabaseAuthService | None = None,
        email: EmailService | None = None,
    ) -> None:
        self._session = session
        self._supabase = supabase or SupabaseAuthService()
        self._email = email or EmailService()

    async def provision_from_stripe_activation(
        self, provisioning_request_id: int
    ) -> TenantProvisioningRequest:
        req = await self._session.get(
            TenantProvisioningRequest, provisioning_request_id
        )
        if req is None:
            raise OnboardingError(f"provisioning request {provisioning_request_id} not found")

        # Idempotency: already done.
        if req.status == "provisioned":
            return req
        # Not yet paid (or terminal-cancelled): do nothing.
        if req.status not in _PROVISIONABLE:
            return req

        req.status = "provisioning"
        await self._session.flush()
        audit.audit(
            audit.TENANT_PROVISIONING_STARTED,
            provisioning_request_id=req.id,
            tier_key=req.tier_key,
            tenant_slug=req.tenant_slug,
        )

        try:
            tenant = await self._ensure_tenant(req)
            invite_link, root_user = await self._ensure_root_admin(req, tenant)
            await self._link_billing(req, tenant)
            await self._run_tier_automation(req, tenant)
            await self._ensure_default_project(req, tenant, root_user)
            await self._send_lifecycle_emails(req, invite_link)

            req.status = "provisioned"
            req.tenant_status = "active"
            req.provisioned_at = datetime.now(UTC)
            await self._session.flush()
            audit.audit(
                audit.TENANT_PROVISIONING_COMPLETED,
                provisioning_request_id=req.id,
                tenant_id=tenant.id,
            )
        except Exception as exc:
            req.status = "failed"
            req.error_message = str(exc)[:500]
            await self._session.flush()
            audit.audit(
                audit.TENANT_PROVISIONING_FAILED,
                provisioning_request_id=req.id,
                error=type(exc).__name__,
            )
            raise
        return req

    # --- steps -------------------------------------------------------------------

    async def _ensure_tenant(self, req: TenantProvisioningRequest) -> Tenant:
        tenant = await self._session.scalar(
            select(Tenant).where(Tenant.slug == req.tenant_slug)
        )
        if tenant is None:
            tenant = Tenant(
                slug=req.tenant_slug,
                name=req.company_name or req.tenant_slug.title(),
            )
            self._session.add(tenant)
            await self._session.flush()
            audit.audit(
                audit.TENANT_CREATED, tenant_id=tenant.id, tenant_slug=tenant.slug
            )
        req.tenant_id = tenant.id
        return tenant

    async def _ensure_root_admin(
        self, req: TenantProvisioningRequest, tenant: Tenant
    ) -> tuple[str | None, User]:
        from app.config import get_settings

        login_url = f"{get_settings().app_base_url}/{tenant.slug}/login"
        supa = await self._supabase.create_or_invite_user(
            req.tenant_admin_email,
            first_name=req.tenant_admin_first_name,
            last_name=req.tenant_admin_last_name,
            redirect_to=login_url,
        )
        if supa.created:
            req.root_admin_status = "supabase_user_created"
            audit.audit(
                audit.SUPABASE_USER_CREATED,
                provisioning_request_id=req.id,
                supabase_user_id=supa.id,
            )
        else:
            req.root_admin_status = "existing_supabase_user_linked"
            audit.audit(
                audit.SUPABASE_EXISTING_USER_LINKED,
                provisioning_request_id=req.id,
                supabase_user_id=supa.id,
            )

        user = await self._supabase.link_local_user(
            self._session,
            supabase_user_id=supa.id,
            email=req.tenant_admin_email,
            tenant_id=tenant.id,
            role="root_admin",
            first_name=req.tenant_admin_first_name,
            last_name=req.tenant_admin_last_name,
        )

        membership = await self._session.scalar(
            select(TenantMembership).where(
                TenantMembership.tenant_id == tenant.id,
                TenantMembership.user_id == user.id,
            )
        )
        if membership is None:
            membership = TenantMembership(
                tenant_id=tenant.id, user_id=user.id, role="root_admin"
            )
            self._session.add(membership)
            await self._session.flush()
            audit.audit(
                audit.TENANT_MEMBERSHIP_CREATED,
                tenant_id=tenant.id,
                user_id=user.id,
                role="root_admin",
            )
        elif membership.role != "root_admin":
            membership.role = "root_admin"
        req.root_admin_status = "membership_created"
        return supa.action_link, user

    async def _link_billing(
        self, req: TenantProvisioningRequest, tenant: Tenant
    ) -> None:
        if req.stripe_customer_id:
            customer = await self._session.scalar(
                select(BillingCustomer).where(
                    BillingCustomer.stripe_customer_id == req.stripe_customer_id
                )
            )
            if customer is not None:
                customer.tenant_id = tenant.id
                req.billing_customer_id = customer.id
        if req.stripe_subscription_id:
            sub = await self._session.scalar(
                select(BillingSubscription).where(
                    BillingSubscription.stripe_subscription_id
                    == req.stripe_subscription_id
                )
            )
            if sub is not None:
                sub.tenant_id = tenant.id
                req.billing_subscription_id = sub.id
        req.billing_status = "active"
        await self._session.flush()

    async def _run_tier_automation(
        self, req: TenantProvisioningRequest, tenant: Tenant
    ) -> None:
        if req.tier_key == "basic_cloud":
            req.data_plane_status = "shared_cloud_bound"
            req.vpn_status = "not_required"
            await self._session.flush()
            audit.audit(
                audit.SHARED_CLOUD_BOUND, tenant_id=tenant.id, tenant_slug=tenant.slug
            )
            return

        # Isolated tiers run the real data-plane provisioning automation.
        audit.audit(
            audit.ISOLATED_DATA_PLANE_STARTED,
            tenant_id=tenant.id,
            tenant_slug=tenant.slug,
            requires_vpn=req.requires_vpn,
        )
        req.data_plane_status = "provisioning"
        await self._session.flush()

        provisioner = TenantProvisioningService(self._session)
        vpn_mode = "customer_vpn" if req.requires_vpn else "none"
        try:
            await provisioner.create(
                tenant_id=tenant.slug,
                tenant_name=tenant.name,
                allowed_onprem_cidrs=[],
                org_tenant_id=tenant.id,
                routing_type="static",
                vpn_mode=vpn_mode,
            )
        except TenantAlreadyExists:
            # Idempotent replay: data plane already exists.
            pass

        req.data_plane_status = "provisioned"
        audit.audit(
            audit.ISOLATED_DATA_PLANE_PROVISIONED,
            tenant_id=tenant.id,
            tenant_slug=tenant.slug,
        )

        if req.requires_vpn:
            req.vpn_status = "awaiting_customer_network_details"
            audit.audit(audit.VPN_AWS_SIDE_PROVISIONED, tenant_id=tenant.id)
            audit.audit(audit.VPN_AWAITING_CUSTOMER_DETAILS, tenant_id=tenant.id)
        else:
            req.vpn_status = "not_required"
        await self._session.flush()

    async def _ensure_default_project(
        self, req: TenantProvisioningRequest, tenant: Tenant, owner: User
    ) -> None:
        existing = await self._session.scalar(
            select(Project).where(Project.tenant_id == tenant.id)
        )
        if existing is None:
            project = Project(
                tenant_id=tenant.id,
                owner_id=owner.id,
                name=f"{tenant.name} Workspace",
                description="Default workspace",
            )
            self._session.add(project)
            await self._session.flush()

    async def _send_lifecycle_emails(
        self, req: TenantProvisioningRequest, invite_link: str | None
    ) -> None:
        from app.config import get_settings

        settings = get_settings()
        login_url = f"{settings.app_base_url}/{req.tenant_slug}/login"
        tier_display = req.tier_key.replace("_", " ").title()

        invite = render_root_admin_invite(
            company_name=req.company_name or req.tenant_slug,
            tier_display=tier_display,
            invite_link=invite_link,
            login_url=login_url,
        )
        sent = await self._email.send(
            invite, to=req.tenant_admin_email, template="root_admin_invite"
        )
        if sent:
            req.root_admin_status = "invite_sent"
            audit.audit(
                audit.ROOT_ADMIN_INVITE_SENT,
                provisioning_request_id=req.id,
                recipient=req.tenant_admin_email,
            )

        if req.vpn_status == "awaiting_customer_network_details":
            onboarding_url = f"{settings.app_base_url}/onboarding/vpn?request={req.id}"
            vpn_email = render_vpn_info_required(
                company_name=req.company_name or req.tenant_slug,
                onboarding_url=onboarding_url,
            )
            await self._email.send(
                vpn_email, to=req.tenant_admin_email, template="vpn_info_required"
            )
        else:
            ready = render_tenant_ready(
                company_name=req.company_name or req.tenant_slug,
                login_url=login_url,
            )
            await self._email.send(
                ready, to=req.tenant_admin_email, template="tenant_ready"
            )
