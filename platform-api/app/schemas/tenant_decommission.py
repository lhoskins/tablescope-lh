"""Pydantic schemas for the tenant decommission workflow."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DecommissionPreviewRequest(BaseModel):
    tenant_id: int = Field(..., description="Organization tenant id to decommission.")
    reason: str = Field(..., min_length=1)


class DecommissionPreviewResponse(BaseModel):
    tenant_id: int
    tenant_slug: str
    tenant_name: str
    data_plane_tenant_id: str | None
    vpn_mode: str | None
    can_decommission: bool
    blockers: list[str]
    resource_summary: dict
    dependency_summary: dict
    is_last_terraform_tenant: bool | None
    protected_tenant: bool
    confirmation_phrase: str


class DecommissionRequest(BaseModel):
    tenant_id: int
    reason: str = Field(..., min_length=1)
    confirmation: str = Field(..., min_length=1)
    idempotency_key: str = Field(..., min_length=1)


class DecommissionApproveRequest(BaseModel):
    confirmation: str = Field(..., min_length=1)
    plan_sha256: str | None = None


class DecommissionJobSummary(BaseModel):
    id: str
    tenant_pk: int
    tenant_slug: str
    data_plane_tenant_id: str | None
    status: str
    current_step: str
    requested_by: int
    approved_by: int | None
    reason: str
    attempt: int
    error_code: str | None
    error_message_safe: str | None
    requested_at: str | None
    frozen_at: str | None
    approved_at: str | None
    terraform_applied_at: str | None
    aws_verified_at: str | None
    runtime_cleaned_at: str | None
    data_cleaned_at: str | None
    completed_at: str | None
    created_at: str
    updated_at: str


class DecommissionJobDetail(DecommissionJobSummary):
    resource_snapshot: dict | None
    dependency_snapshot: dict | None
    verification_results: dict | None
    terraform_plan_summary: dict | None


class DecommissionEventRead(BaseModel):
    id: int
    step: str
    status: str
    actor_type: str
    actor_id: str | None
    correlation_id: str | None
    safe_details: dict | None
    created_at: str


class DecommissionRunnerCallback(BaseModel):
    job_id: str
    step: str
    status: str
    safe_details: dict | None = None
    error_code: str | None = None
    error_message_safe: str | None = None


class TerraformPlanSummary(BaseModel):
    plan_sha256: str | None
    terraform_plan_summary: dict | None
    resource_changes: list[dict]
    proposed_destroy: list[str]
    proposed_update: list[str]
    shared_hub_would_be_destroyed: bool
    other_tenant_affected: bool
    validation_errors: list[str]


class DecommissionRetryResponse(BaseModel):
    job_id: str
    status: str
    current_step: str
    message: str
