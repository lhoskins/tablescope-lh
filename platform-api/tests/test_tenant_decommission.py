"""Tests for the orchestrated tenant decommission workflow."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant
from app.models.tenant_data_plane import TenantDataPlane
from app.models.tenant_decommission import TenantDecommissionEvent
from app.models.user import User
from app.services.tenant_decommission_runner import (
    RunnerAuthError,
    create_runner_payload,
    verify_runner_payload,
)
from app.services.tenant_decommission_service import (
    STATUS_AWAITING_APPROVAL,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_TENANT_FROZEN,
    STATUS_TERRAFORM_PLAN_REJECTED,
    DecommissionError,
    TenantDecommissionService,
)
from app.services.terraform_plan_policy import validate_terraform_plan


async def _seed(db: AsyncSession, *, slug: str = "decomm-test", vpn_mode: str = "none", extra_vpn_plane: bool = False) -> tuple:
    tenant = Tenant(slug=slug, name="Decomm Test", is_active=True)
    db.add(tenant)
    await db.flush()

    admin = User(
        tenant_id=tenant.id,
        email=f"admin-{slug}@example.com",
        display_name="Admin",
        role="admin",
        is_active=True,
    )
    approver = User(
        tenant_id=tenant.id,
        email=f"approver-{slug}@example.com",
        display_name="Approver",
        role="admin",
        is_active=True,
    )
    db.add_all([admin, approver])
    await db.flush()

    if vpn_mode:
        plane = TenantDataPlane(
            tenant_id=slug,
            tenant_name="Decomm Test",
            org_tenant_id=tenant.id,
            vpn_mode=vpn_mode,
            docker_network_name=f"tenant_{slug}_net",
            docker_subnet_cidr="172.30.20.0/24",
            teiid_container_name=f"tenant-{slug}-teiid",
            teiid_container_ip="172.30.20.10",
            teiid_servlet_url="http://127.0.0.1:28095",
            teiid_pg_host="127.0.0.1",
            teiid_pg_port=25442,
            vdb_host_path=f"/opt/tablescope/{slug}/vdb",
            vdb_container_path="/opt/wildfly/teiidfiles/customers",
            allowed_onprem_cidrs=["10.0.0.0/16"] if vpn_mode == "customer_vpn" else [],
            status="provisioned",
        )
        db.add(plane)
        await db.flush()

    if extra_vpn_plane and vpn_mode == "customer_vpn":
        other = TenantDataPlane(
            tenant_id="other",
            tenant_name="Other",
            org_tenant_id=None,
            vpn_mode="customer_vpn",
            docker_network_name="tenant_other_net",
            docker_subnet_cidr="172.30.30.0/24",
            teiid_container_name="tenant-other-teiid",
            teiid_container_ip="172.30.30.10",
            teiid_servlet_url="http://127.0.0.1:38095",
            teiid_pg_host="127.0.0.1",
            teiid_pg_port=35442,
            vdb_host_path="/opt/tablescope/other/vdb",
            vdb_container_path="/opt/wildfly/teiidfiles/customers",
            allowed_onprem_cidrs=["10.10.0.0/16"],
            status="provisioned",
        )
        db.add(other)
        await db.flush()

    await db.commit()
    return tenant, admin, approver


async def _service(db: AsyncSession) -> TenantDecommissionService:
    return TenantDecommissionService(db)


@pytest.mark.asyncio
async def test_preview_protects_root_slug(db_session: AsyncSession) -> None:
    tenant, *_ = await _seed(db_session, slug="root")
    svc = await _service(db_session)
    preview = await svc.preview(tenant.id, "test reason")
    assert preview["protected_tenant"] is True
    assert preview["can_decommission"] is False
    assert any("protected" in b for b in preview["blockers"])


@pytest.mark.asyncio
async def test_request_freezes_tenant(db_session: AsyncSession) -> None:
    tenant, admin, approver = await _seed(db_session, slug="freeze-me")
    svc = await _service(db_session)
    job = await svc.request(
        tenant.id,
        reason="ticket-123",
        confirmation="DECOMMISSION freeze-me",
        idempotency_key=str(uuid.uuid4()),
        requested_by=admin.id,
        application_sha="app-sha",
        infrastructure_sha="infra-sha",
    )
    assert job.status == STATUS_TENANT_FROZEN
    assert job.current_step == "preflight"

    await db_session.refresh(tenant)
    assert tenant.lifecycle_status == "decommissioning"
    assert tenant.is_active is False
    assert tenant.activity_blocked_at is not None
    assert tenant.decommission_job_id == job.id

    events = list(
        (
            await db_session.scalars(
                select(TenantDecommissionEvent).where(
                    TenantDecommissionEvent.job_id == job.id
                )
            )
        ).all()
    )
    assert len(events) >= 2


@pytest.mark.asyncio
async def test_approval_requires_awaiting_status(db_session: AsyncSession) -> None:
    tenant, admin, approver = await _seed(db_session, slug="approve-me")
    svc = await _service(db_session)
    job = await svc.request(
        tenant.id,
        reason="ticket-123",
        confirmation="DECOMMISSION approve-me",
        idempotency_key=str(uuid.uuid4()),
        requested_by=admin.id,
        application_sha="app-sha",
        infrastructure_sha="infra-sha",
    )
    with pytest.raises(DecommissionError, match="not ready for approval"):
        await svc.approve(
            job.id,
            approved_by=approver.id,
            confirmation="DECOMMISSION approve-me",
            plan_sha256=None,
        )


@pytest.mark.asyncio
async def test_runner_plan_callback_validates_plan(db_session: AsyncSession) -> None:
    tenant, admin, approver = await _seed(
        db_session, slug="plan-test", vpn_mode="customer_vpn", extra_vpn_plane=True
    )
    svc = await _service(db_session)
    job = await svc.request(
        tenant.id,
        reason="ticket-123",
        confirmation="DECOMMISSION plan-test",
        idempotency_key=str(uuid.uuid4()),
        requested_by=admin.id,
        application_sha="app-sha",
        infrastructure_sha="infra-sha",
    )
    assert job.status == STATUS_TENANT_FROZEN

    # Plan that deletes the target module plus a shared route keyed for target.
    plan = {
        "resource_changes": [
            {
                "address": 'module.tenant["plan-test"].aws_vpc.tenant',
                "mode": "managed",
                "type": "aws_vpc",
                "change": {
                    "actions": ["delete"],
                    "before": {
                        "tags": {
                            "Tenant": "plan-test",
                            "ManagedBy": "tablescope-tenant-dataplane",
                        }
                    },
                },
            },
            {
                "address": 'module.network_hub[0].aws_route.shared_to_tgw["plan-test-0"]',
                "mode": "managed",
                "type": "aws_route",
                "change": {
                    "actions": ["delete"],
                    "before": {"destination_cidr_block": "10.0.0.0/16"},
                },
            },
        ]
    }
    await svc.runner_callback(
        job.id,
        step="terraform_plan",
        status="succeeded",
        actor_id="runner-1",
        safe_details={
            "plan_json": plan,
            "plan_sha256": "abc123",
            "plan_storage_key": "s3://bucket/plan",
        },
    )
    await db_session.refresh(job)
    assert job.status == STATUS_AWAITING_APPROVAL
    assert job.terraform_plan_sha256 == "abc123"


@pytest.mark.asyncio
async def test_runner_callback_rejects_other_tenant_plan(db_session: AsyncSession) -> None:
    tenant, admin, _ = await _seed(
        db_session, slug="reject-test", vpn_mode="customer_vpn", extra_vpn_plane=True
    )
    svc = await _service(db_session)
    job = await svc.request(
        tenant.id,
        reason="ticket-123",
        confirmation="DECOMMISSION reject-test",
        idempotency_key=str(uuid.uuid4()),
        requested_by=admin.id,
        application_sha="app-sha",
        infrastructure_sha="infra-sha",
    )
    plan = {
        "resource_changes": [
            {
                "address": 'module.tenant["other"].aws_vpc.tenant',
                "mode": "managed",
                "type": "aws_vpc",
                "change": {
                    "actions": ["delete"],
                    "before": {
                        "tags": {
                            "Tenant": "other",
                            "ManagedBy": "tablescope-tenant-dataplane",
                        }
                    },
                },
            },
        ]
    }
    await svc.runner_callback(
        job.id,
        step="terraform_plan",
        status="succeeded",
        actor_id="runner-1",
        safe_details={"plan_json": plan},
    )
    await db_session.refresh(job)
    assert job.status == STATUS_TERRAFORM_PLAN_REJECTED


@pytest.mark.asyncio
async def test_cancel_unfreezes_tenant(db_session: AsyncSession) -> None:
    tenant, admin, _ = await _seed(db_session, slug="cancel-me")
    svc = await _service(db_session)
    job = await svc.request(
        tenant.id,
        reason="ticket-123",
        confirmation="DECOMMISSION cancel-me",
        idempotency_key=str(uuid.uuid4()),
        requested_by=admin.id,
        application_sha="app-sha",
        infrastructure_sha="infra-sha",
    )
    cancelled = await svc.cancel(job.id, admin.id)
    assert cancelled.status == STATUS_CANCELLED

    await db_session.refresh(tenant)
    assert tenant.lifecycle_status == "active"
    assert tenant.is_active is True
    assert tenant.decommission_job_id is None


@pytest.mark.asyncio
async def test_complete_decommission_lifecycle(db_session: AsyncSession) -> None:
    tenant, admin, approver = await _seed(
        db_session, slug="complete-me", vpn_mode="customer_vpn", extra_vpn_plane=True
    )
    svc = await _service(db_session)
    job = await svc.request(
        tenant.id,
        reason="ticket-123",
        confirmation="DECOMMISSION complete-me",
        idempotency_key=str(uuid.uuid4()),
        requested_by=admin.id,
        application_sha="app-sha",
        infrastructure_sha="infra-sha",
    )

    plan = {
        "resource_changes": [
            {
                "address": 'module.tenant["complete-me"].aws_vpc.tenant',
                "mode": "managed",
                "type": "aws_vpc",
                "change": {
                    "actions": ["delete"],
                    "before": {
                        "tags": {
                            "Tenant": "complete-me",
                            "ManagedBy": "tablescope-tenant-dataplane",
                        }
                    },
                },
            }
        ]
    }
    await svc.runner_callback(
        job.id,
        step="terraform_plan",
        status="succeeded",
        actor_id="runner-1",
        safe_details={"plan_json": plan, "plan_sha256": "abc"},
    )
    await svc.approve(
        job.id,
        approved_by=approver.id,
        confirmation="DECOMMISSION complete-me",
        plan_sha256="abc",
    )
    for step in ["terraform_apply", "aws_verification", "runtime_cleanup", "data_cleanup"]:
        await svc.runner_callback(
            job.id,
            step=step,
            status="succeeded",
            actor_id="runner-1",
            safe_details={},
        )
        await db_session.refresh(job)

    await db_session.refresh(job)
    assert job.status == STATUS_COMPLETED
    assert job.completed_at is not None

    await db_session.refresh(tenant)
    assert tenant.lifecycle_status == "decommissioned"
    assert tenant.decommissioned_at is not None


class TestRunnerContract:
    def test_round_trip_payload(self) -> None:
        payload = create_runner_payload(
            job_id="job-123",
            tenant_slug="acme",
            data_plane_tenant_id="acme",
            state_key="terraform_plan",
            application_sha="app-sha",
            infrastructure_sha="infra-sha",
            expected_aws_ids={"aws_vpc": "vpc-123"},
        )
        verified = verify_runner_payload(payload.to_dict())
        assert verified.job_id == "job-123"
        assert verified.state_key == "terraform_plan"
        assert verified.expected_aws_ids["aws_vpc"] == "vpc-123"

    def test_tampered_payload_rejected(self) -> None:
        payload = create_runner_payload(
            job_id="job-123",
            tenant_slug="acme",
            data_plane_tenant_id="acme",
            state_key="terraform_plan",
            application_sha="app-sha",
            infrastructure_sha="infra-sha",
        )
        data = payload.to_dict()
        data["state_key"] = "data_cleanup"
        with pytest.raises(RunnerAuthError):
            verify_runner_payload(data)


class TestTerraformPlanPolicy:
    def test_accepts_target_module_and_shared_routes(self) -> None:
        plan = {
            "resource_changes": [
                {
                    "address": 'module.tenant["acme"].aws_vpc.tenant',
                    "change": {
                        "actions": ["delete"],
                        "before": {
                            "tags": {
                                "Tenant": "acme",
                                "ManagedBy": "tablescope-tenant-dataplane",
                            }
                        },
                    },
                },
                {
                    "address": 'module.network_hub[0].aws_route.shared_to_tgw["acme-0"]',
                    "change": {"actions": ["delete"], "before": {}},
                },
            ]
        }
        result = validate_terraform_plan(
            plan, target_tenant_id="acme", target_onprem_cidrs=["10.0.0.0/16"]
        )
        assert result.valid is True
        assert result.shared_hub_would_be_destroyed is False
        assert result.other_tenant_affected is False

    def test_rejects_other_tenant_resource(self) -> None:
        plan = {
            "resource_changes": [
                {
                    "address": 'module.tenant["other"].aws_vpc.tenant',
                    "change": {
                        "actions": ["delete"],
                        "before": {
                            "tags": {
                                "Tenant": "other",
                                "ManagedBy": "tablescope-tenant-dataplane",
                            }
                        },
                    },
                }
            ]
        }
        result = validate_terraform_plan(
            plan, target_tenant_id="acme", target_onprem_cidrs=[]
        )
        assert result.valid is False
        assert result.other_tenant_affected is True

    def test_rejects_shared_hub_destruction(self) -> None:
        plan = {
            "resource_changes": [
                {
                    "address": 'module.network_hub[0].aws_ec2_transit_gateway.hub',
                    "change": {"actions": ["delete"], "before": {}},
                }
            ]
        }
        result = validate_terraform_plan(
            plan, target_tenant_id="acme", target_onprem_cidrs=[]
        )
        assert result.valid is False
        assert result.shared_hub_would_be_destroyed is True

    def test_rejects_create_or_replace(self) -> None:
        plan = {
            "resource_changes": [
                {
                    "address": 'module.tenant["acme"].aws_vpc.tenant',
                    "change": {"actions": ["create"]},
                }
            ]
        }
        result = validate_terraform_plan(
            plan, target_tenant_id="acme", target_onprem_cidrs=[]
        )
        assert result.valid is False
