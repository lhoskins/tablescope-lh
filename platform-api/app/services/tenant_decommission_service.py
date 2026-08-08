"""Tenant decommission state-machine orchestration service."""

from __future__ import annotations

import ipaddress
import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.tenant import Tenant
from app.models.tenant_data_plane import TenantDataPlane
from app.models.tenant_decommission import TenantDecommissionEvent, TenantDecommissionJob
from app.services.tenant_decommission_inventory import (
    TenantDependencyInventory,
    collect_tenant_dependency_inventory,
    inventory_to_dict,
)
from app.services.tenant_decommission_state import (
    STATUS_AWAITING_APPROVAL,
    STATUS_AWS_DESTROYED,
    STATUS_AWS_VERIFICATION_FAILED,
    STATUS_AWS_VERIFICATION_RUNNING,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_DATA_CLEANUP_FAILED,
    STATUS_DATA_CLEANUP_RUNNING,
    STATUS_PREFLIGHT_BLOCKED,
    STATUS_PREFLIGHT_RUNNING,
    STATUS_RUNTIME_CLEANUP_FAILED,
    STATUS_RUNTIME_CLEANUP_RUNNING,
    STATUS_TENANT_FROZEN,
    STATUS_TERRAFORM_APPLY_FAILED,
    STATUS_TERRAFORM_APPLY_RUNNING,
    STATUS_TERRAFORM_PLAN_REJECTED,
    STATUS_TERRAFORM_PLAN_RUNNING,
    DecommissionError,
    can_transition,
)
from app.services.tenant_layout import TenantLayout, compute_layout
from app.services.terraform_plan_policy import (
    PlanPolicyError,
    validate_terraform_plan,
)

CONFIRMATION_PATTERN = re.compile(r"^DECOMMISSION\s+([a-z0-9-]+)$", re.IGNORECASE)


def _parse_index_from_cidr(cidr: str) -> int:
    """Infer the deterministic tenant index from its Docker subnet."""
    net = ipaddress.ip_network(cidr, strict=False)
    octets = str(net.network_address).split(".")
    third = int(octets[2])
    if third % 10 != 0:
        raise ValueError(f"unexpected tenant subnet {cidr}")
    return third // 10


def _layout_from_data_plane(plane: TenantDataPlane) -> TenantLayout:
    index = _parse_index_from_cidr(plane.docker_subnet_cidr)
    return compute_layout(plane.tenant_id, index)


def _now() -> datetime:
    return datetime.now(UTC)


class TenantDecommissionService:
    """Coordinate the full lifecycle of a tenant decommission job."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def _protected_slugs(self) -> set[str]:
        base = {"root", "tablescope", "platform", "devin", "admin"}
        configured = get_settings().protected_tenant_slugs
        if configured:
            base.update(s.strip().lower() for s in configured.split(",") if s.strip())
        return base

    async def _get_tenant(self, tenant_id: int) -> Tenant:
        tenant = await self._session.get(Tenant, tenant_id)
        if tenant is None:
            raise DecommissionError("Tenant not found.", "TENANT_NOT_FOUND")
        return tenant

    async def _get_plane(self, tenant: Tenant) -> TenantDataPlane | None:
        return await self._session.scalar(
            select(TenantDataPlane).where(
                TenantDataPlane.org_tenant_id == tenant.id
            )
        )

    async def _active_job(self, tenant: Tenant) -> TenantDecommissionJob | None:
        return await self._session.scalar(
            select(TenantDecommissionJob)
            .where(
                TenantDecommissionJob.tenant_pk == tenant.id,
                TenantDecommissionJob.status.not_in([STATUS_COMPLETED, STATUS_CANCELLED]),
            )
            .order_by(TenantDecommissionJob.created_at.desc())
            .limit(1)
        )

    async def _get_job(self, job_id: str) -> TenantDecommissionJob:
        job = await self._session.get(TenantDecommissionJob, job_id)
        if job is None:
            raise DecommissionError("Decommission job not found.", "JOB_NOT_FOUND")
        return job

    def _confirmation_for(self, slug: str) -> str:
        return f"DECOMMISSION {slug}"

    def _validate_confirmation(
        self, confirmation: str, slug: str, phrase: str
    ) -> None:
        match = CONFIRMATION_PATTERN.match(confirmation or "")
        if not match:
            raise DecommissionError(
                "Typed confirmation must be 'DECOMMISSION <tenant_slug>'.",
                "INVALID_CONFIRMATION",
            )
        if match.group(1).lower() != slug.lower():
            raise DecommissionError(
                "Confirmation does not match the tenant slug.",
                "CONFIRMATION_MISMATCH",
            )
        if phrase and confirmation != phrase:
            # This is a defense-in-depth exact-match check.
            raise DecommissionError(
                "Confirmation does not match the expected phrase.",
                "CONFIRMATION_MISMATCH",
            )

    async def _check_blockers(
        self,
        tenant: Tenant,
        plane: TenantDataPlane | None,
        inventory: TenantDependencyInventory,
        require_no_active_job: bool = True,
    ) -> list[str]:
        blockers: list[str] = []

        if tenant.slug.lower() in self._protected_slugs:
            blockers.append(f"Tenant '{tenant.slug}' is protected and cannot be decommissioned.")

        if tenant.lifecycle_status in ("decommissioning", "decommissioned"):
            blockers.append("Tenant is already decommissioning or decommissioned.")

        if inventory.has_active_billing_subscription:
            blockers.append("Active billing subscription exists; cancel before decommission.")

        if plane and plane.vpn_mode == "customer_vpn":
            other_active = await self._session.scalar(
                select(TenantDataPlane.id)
                .where(
                    TenantDataPlane.vpn_mode == "customer_vpn",
                    TenantDataPlane.status != "decommissioned",
                    TenantDataPlane.id != plane.id,
                )
                .limit(1)
            )
            if other_active is None:
                blockers.append(
                    "This is the last customer-VPN tenant. Removing it would destroy the shared network hub. Use the shared-hub retirement workflow instead."
                )

        if require_no_active_job:
            active = await self._active_job(tenant)
            if active is not None:
                blockers.append(f"Active decommission job already exists: {active.id}.")

        return blockers

    async def preview(
        self,
        tenant_id: int,
        reason: str,
    ) -> dict:
        tenant = await self._get_tenant(tenant_id)
        plane = await self._get_plane(tenant)
        inventory = await collect_tenant_dependency_inventory(self._session, tenant_id)
        blockers = await self._check_blockers(tenant, plane, inventory)

        resource_summary = {}
        if plane is not None:
            resource_summary = plane.to_dict(include_network=True)
            resource_summary["layout"] = {}
            try:
                layout = _layout_from_data_plane(plane)
                resource_summary["layout"] = {
                    "docker_network_name": layout.docker_network_name,
                    "teiid_container_name": layout.teiid_container_name,
                    "tenant_root": layout.tenant_root,
                    "vdb_host_path": layout.vdb_host_path,
                    "compose_host_path": layout.compose_host_path,
                    "firewall_chain": layout.firewall_chain,
                }
            except Exception:
                resource_summary["layout"] = {}

        is_last_vpn = None
        if plane and plane.vpn_mode == "customer_vpn":
            total = await self._session.scalar(
                select(func.count(TenantDataPlane.id)).where(
                    TenantDataPlane.vpn_mode == "customer_vpn",
                    TenantDataPlane.status != "decommissioned",
                )
            )
            is_last_vpn = total == 1

        return {
            "tenant_id": tenant.id,
            "tenant_slug": tenant.slug,
            "tenant_name": tenant.name,
            "data_plane_tenant_id": plane.tenant_id if plane else None,
            "vpn_mode": plane.vpn_mode if plane else None,
            "can_decommission": len(blockers) == 0,
            "blockers": blockers,
            "resource_summary": resource_summary,
            "dependency_summary": inventory_to_dict(inventory),
            "is_last_terraform_tenant": is_last_vpn,
            "protected_tenant": tenant.slug.lower() in self._protected_slugs,
            "confirmation_phrase": self._confirmation_for(tenant.slug),
        }

    async def request(
        self,
        tenant_id: int,
        reason: str,
        confirmation: str,
        idempotency_key: str,
        requested_by: int,
        application_sha: str,
        infrastructure_sha: str,
    ) -> TenantDecommissionJob:
        tenant = await self._get_tenant(tenant_id)
        plane = await self._get_plane(tenant)
        inventory = await collect_tenant_dependency_inventory(self._session, tenant_id)

        if not reason or not reason.strip():
            raise DecommissionError("A reason/ticket number is required.", "REASON_REQUIRED")

        phrase = self._confirmation_for(tenant.slug)
        self._validate_confirmation(confirmation, tenant.slug, phrase)

        blockers = await self._check_blockers(tenant, plane, inventory)
        if blockers:
            raise DecommissionError(
                "Cannot request decommission: " + "; ".join(blockers),
                "PREFLIGHT_BLOCKED",
            )

        existing = await self._active_job(tenant)
        if existing is not None:
            raise DecommissionError(
                f"Active decommission job already exists: {existing.id}.",
                "ACTIVE_JOB_EXISTS",
            )

        duplicate = await self._session.scalar(
            select(TenantDecommissionJob.id).where(
                TenantDecommissionJob.idempotency_key == idempotency_key
            )
        )
        if duplicate is not None:
            raise DecommissionError(
                "Idempotency key has already been used.", "DUPLICATE_IDEMPOTENCY_KEY"
            )

        requested_at = _now()
        job = TenantDecommissionJob(
            id=str(uuid.uuid4()),
            tenant_pk=tenant.id,
            tenant_slug=tenant.slug,
            data_plane_tenant_id=plane.tenant_id if plane else None,
            requested_by=requested_by,
            reason=reason.strip(),
            status=STATUS_TENANT_FROZEN,
            current_step="preflight",
            idempotency_key=idempotency_key,
            confirmation_phrase=phrase,
            application_sha=application_sha,
            infrastructure_sha=infrastructure_sha,
            resource_snapshot=plane.to_dict(include_network=True) if plane else None,
            dependency_snapshot=inventory_to_dict(inventory),
            requested_at=requested_at,
            frozen_at=requested_at,
        )
        self._session.add(job)

        tenant.lifecycle_status = "decommissioning"
        tenant.is_active = False
        tenant.activity_blocked_at = requested_at
        tenant.decommission_job_id = job.id

        if plane is not None:
            plane.decommission_job_id = job.id
            plane.status = "decommissioning"

        await self._session.flush()
        await self.record_event(
            job, "preflight", "succeeded", actor_type="user", actor_id=str(requested_by)
        )
        await self.record_event(
            job,
            "tenant_frozen",
            "succeeded",
            actor_type="user",
            actor_id=str(requested_by),
            safe_details={"tenant_id": tenant.id, "slug": tenant.slug},
        )
        return job

    async def approve(
        self,
        job_id: str,
        approved_by: int,
        confirmation: str,
        plan_sha256: str | None,
    ) -> TenantDecommissionJob:
        job = await self._get_job(job_id)
        if job.approved_by is not None:
            raise DecommissionError("Job has already been approved.", "ALREADY_APPROVED")

        if job.requested_by == approved_by:
            raise DecommissionError(
                "Approver must be different from the requester.", "APPROVER_IS_REQUESTER"
            )

        self._validate_confirmation(confirmation, job.tenant_slug, job.confirmation_phrase)

        if job.status != STATUS_AWAITING_APPROVAL:
            raise DecommissionError(
                "Plan is not ready for approval.", "NOT_AWAITING_APPROVAL"
            )

        if plan_sha256 and job.terraform_plan_sha256:
            if plan_sha256 != job.terraform_plan_sha256:
                raise DecommissionError(
                    "Provided plan hash does not match the stored plan.",
                    "PLAN_HASH_MISMATCH",
                )

        approved_at = _now()
        job.approved_by = approved_by
        job.approved_at = approved_at
        job.status = STATUS_TERRAFORM_APPLY_RUNNING
        job.current_step = "terraform_apply"
        await self.record_event(
            job,
            "approval",
            "succeeded",
            actor_type="user",
            actor_id=str(approved_by),
            safe_details={"plan_sha256": plan_sha256},
        )
        return job

    async def cancel(self, job_id: str, cancelled_by: int) -> TenantDecommissionJob:
        job = await self._get_job(job_id)
        if not can_transition(job.status, STATUS_CANCELLED):
            raise DecommissionError(
                f"Cannot cancel job in status {job.status}.",
                "CANCEL_NOT_ALLOWED",
            )
        return await self._do_cancel(job, cancelled_by, "user")

    async def _do_cancel(
        self,
        job: TenantDecommissionJob,
        actor_id: int,
        actor_type: str,
    ) -> TenantDecommissionJob:
        job.status = STATUS_CANCELLED
        job.current_step = "cancelled"
        job.completed_at = _now()

        tenant = await self._session.get(Tenant, job.tenant_pk)
        if tenant is not None:
            tenant.lifecycle_status = "active"
            tenant.is_active = True
            tenant.activity_blocked_at = None
            tenant.decommission_job_id = None

        plane = await self._session.scalar(
            select(TenantDataPlane).where(
                TenantDataPlane.decommission_job_id == job.id
            )
        )
        if plane is not None:
            plane.decommission_job_id = None
            plane.status = "provisioned"

        await self.record_event(
            job,
            "cancel",
            "succeeded",
            actor_type=actor_type,
            actor_id=str(actor_id),
        )
        return job

    async def unfreeze(
        self,
        job_id: str,
        actor_id: int,
    ) -> TenantDecommissionJob:
        job = await self._get_job(job_id)
        if job.status not in (STATUS_CANCELLED, STATUS_PREFLIGHT_BLOCKED):
            raise DecommissionError(
                "Unfreeze is only allowed for cancelled or preflight-blocked jobs.",
                "UNFREEZE_NOT_ALLOWED",
            )

        tenant = await self._session.get(Tenant, job.tenant_pk)
        if tenant is not None:
            tenant.lifecycle_status = "active"
            tenant.is_active = True
            tenant.activity_blocked_at = None
            tenant.decommission_job_id = None

        plane = await self._session.scalar(
            select(TenantDataPlane).where(
                TenantDataPlane.decommission_job_id == job.id
            )
        )
        if plane is not None:
            plane.decommission_job_id = None
            plane.status = "provisioned"

        await self.record_event(
            job,
            "unfreeze",
            "succeeded",
            actor_type="user",
            actor_id=str(actor_id),
        )
        return job

    async def retry(self, job_id: str, actor_id: int) -> TenantDecommissionJob:
        job = await self._get_job(job_id)
        if job.status in (STATUS_COMPLETED, STATUS_CANCELLED):
            raise DecommissionError("Cannot retry a terminal job.", "TERMINAL_JOB")

        mapping = {
            STATUS_PREFLIGHT_BLOCKED: (STATUS_PREFLIGHT_RUNNING, "preflight"),
            STATUS_TERRAFORM_PLAN_REJECTED: (STATUS_TERRAFORM_PLAN_RUNNING, "terraform_plan"),
            STATUS_AWAITING_APPROVAL: (STATUS_TERRAFORM_PLAN_RUNNING, "terraform_plan"),
            STATUS_TERRAFORM_APPLY_FAILED: (STATUS_TERRAFORM_APPLY_RUNNING, "terraform_apply"),
            STATUS_AWS_VERIFICATION_FAILED: (STATUS_AWS_VERIFICATION_RUNNING, "aws_verification"),
            STATUS_RUNTIME_CLEANUP_FAILED: (STATUS_RUNTIME_CLEANUP_RUNNING, "runtime_cleanup"),
            STATUS_DATA_CLEANUP_FAILED: (STATUS_DATA_CLEANUP_RUNNING, "data_cleanup"),
        }

        new_status, step = mapping.get(job.status, (job.status, job.current_step))
        if not can_transition(job.status, new_status):
            raise DecommissionError(
                f"Retry not supported from status {job.status}.",
                "RETRY_NOT_ALLOWED",
            )

        job.attempt += 1
        job.status = new_status
        job.current_step = step
        job.error_code = None
        job.error_message_safe = None
        await self.record_event(
            job,
            step,
            "retry",
            actor_type="user",
            actor_id=str(actor_id),
            safe_details={"attempt": job.attempt},
        )
        return job

    async def runner_callback(
        self,
        job_id: str,
        step: str,
        status: str,
        actor_id: str | None,
        safe_details: dict | None = None,
        error_code: str | None = None,
        error_message_safe: str | None = None,
    ) -> TenantDecommissionJob:
        job = await self._get_job(job_id)

        if status == "failed":
            failure_map = {
                "preflight": STATUS_PREFLIGHT_BLOCKED,
                "terraform_plan": STATUS_TERRAFORM_PLAN_REJECTED,
                "terraform_apply": STATUS_TERRAFORM_APPLY_FAILED,
                "aws_verification": STATUS_AWS_VERIFICATION_FAILED,
                "runtime_cleanup": STATUS_RUNTIME_CLEANUP_FAILED,
                "data_cleanup": STATUS_DATA_CLEANUP_FAILED,
            }
            new_status = failure_map.get(step, job.status)
            if not can_transition(job.status, new_status):
                new_status = job.status
            job.status = new_status
            job.current_step = step
            job.error_code = error_code
            job.error_message_safe = error_message_safe
            await self.record_event(
                job, step, "failed", actor_type="runner", actor_id=actor_id, safe_details=safe_details
            )
            return job

        success_map = {
            "preflight": (STATUS_TENANT_FROZEN, "tenant_frozen"),
            "terraform_plan": (STATUS_AWAITING_APPROVAL, "awaiting_approval"),
            "terraform_apply": (STATUS_AWS_VERIFICATION_RUNNING, "aws_verification"),
            "aws_verification": (STATUS_AWS_DESTROYED, "aws_destroyed"),
            "runtime_cleanup": (STATUS_DATA_CLEANUP_RUNNING, "data_cleanup"),
            "data_cleanup": (STATUS_COMPLETED, "completed"),
        }

        if step == "terraform_plan" and safe_details:
            plan_json = safe_details.get("plan_json")
            if plan_json:
                tenant_id = job.data_plane_tenant_id or job.tenant_slug
                cidrs = (
                    (job.resource_snapshot or {}).get("allowed_onprem_cidrs")
                    or safe_details.get("onprem_cidrs")
                    or []
                )
                try:
                    result = validate_terraform_plan(
                        plan_json,
                        target_tenant_id=tenant_id,
                        target_onprem_cidrs=list(cidrs),
                    )
                    if not result.valid:
                        job.status = STATUS_TERRAFORM_PLAN_REJECTED
                        job.current_step = "terraform_plan"
                        job.error_code = "TERRAFORM_PLAN_REJECTED"
                        job.error_message_safe = "; ".join(result.validation_errors)
                        job.terraform_plan_summary = {
                            "valid": False,
                            "validation_errors": result.validation_errors,
                            "proposed_destroy": result.proposed_destroy,
                        }
                        await self.record_event(
                            job,
                            "terraform_plan",
                            "rejected",
                            actor_type="runner",
                            actor_id=actor_id,
                            safe_details={
                                "validation_errors": result.validation_errors,
                                "proposed_destroy": result.proposed_destroy,
                            },
                        )
                        return job
                    job.terraform_plan_summary = {
                        "valid": True,
                        "proposed_destroy": result.proposed_destroy,
                        "proposed_update": result.proposed_update,
                    }
                except PlanPolicyError as exc:
                    job.status = STATUS_TERRAFORM_PLAN_REJECTED
                    job.current_step = "terraform_plan"
                    job.error_code = exc.code
                    job.error_message_safe = exc.message
                    await self.record_event(
                        job,
                        "terraform_plan",
                        "rejected",
                        actor_type="runner",
                        actor_id=actor_id,
                        safe_details={"error": exc.message},
                    )
                    return job
            job.terraform_plan_sha256 = safe_details.get("plan_sha256")
            job.terraform_plan_storage_key = safe_details.get("plan_storage_key")

        if step == "terraform_apply":
            job.terraform_applied_at = _now()

        if step == "aws_verification":
            job.aws_verified_at = _now()
            job.verification_results = safe_details

        if step == "runtime_cleanup":
            job.runtime_cleaned_at = _now()

        if step == "data_cleanup":
            job.data_cleaned_at = _now()

        if step == "data_cleanup":
            job.completed_at = _now()
            tenant = await self._session.get(Tenant, job.tenant_pk)
            if tenant is not None:
                tenant.lifecycle_status = "decommissioned"
                tenant.decommissioned_at = _now()

        new_status, new_step = success_map.get(step, (job.status, job.current_step))
        if can_transition(job.status, new_status):
            job.status = new_status
            job.current_step = new_step

        await self.record_event(
            job, step, status, actor_type="runner", actor_id=actor_id, safe_details=safe_details
        )
        return job

    async def record_event(
        self,
        job: TenantDecommissionJob,
        step: str,
        status: str,
        *,
        actor_type: str,
        actor_id: str | None,
        safe_details: dict | None = None,
        correlation_id: str | None = None,
    ) -> TenantDecommissionEvent:
        event = TenantDecommissionEvent(
            job_id=job.id,
            step=step,
            status=status,
            actor_type=actor_type,
            actor_id=actor_id,
            safe_details=safe_details or {},
            correlation_id=correlation_id,
        )
        self._session.add(event)
        await self._session.flush()
        return event
