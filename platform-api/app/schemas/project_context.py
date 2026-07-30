"""Pydantic schemas for project business context, goals, metrics, targets, and risks."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProjectBusinessContextSettings(BaseModel):
    business_owner_id: int | None = None
    business_function: str | None = Field(default=None, max_length=255)
    industry: str | None = Field(default=None, max_length=255)
    purpose: str | None = Field(default=None, max_length=4000)
    timezone: str = Field(default="UTC", max_length=100)
    currency: str = Field(default="USD", max_length=10)
    reporting_cadence: str | None = Field(default=None, max_length=50)
    fiscal_year_start_month: int | None = Field(default=None, ge=1, le=12)
    ai_context_enabled: bool = True
    ai_instructions: str | None = Field(default=None, max_length=4000)
    interpretation_notes: str | None = Field(default=None, max_length=4000)


class ProjectBusinessContextRead(ProjectBusinessContextSettings):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    tenant_id: int
    version: int
    updated_by: int | None
    created_at: datetime
    updated_at: datetime


class ProjectBusinessContextUpdate(BaseModel):
    business_owner_id: int | None = None
    business_function: str | None = Field(default=None, max_length=255)
    industry: str | None = Field(default=None, max_length=255)
    purpose: str | None = Field(default=None, max_length=4000)
    timezone: str | None = Field(default=None, max_length=100)
    currency: str | None = Field(default=None, max_length=10)
    reporting_cadence: str | None = Field(default=None, max_length=50)
    fiscal_year_start_month: int | None = Field(default=None, ge=1, le=12)
    ai_context_enabled: bool | None = None
    ai_instructions: str | None = Field(default=None, max_length=4000)
    interpretation_notes: str | None = Field(default=None, max_length=4000)
    expected_version: int | None = None


class ConflictResponse(BaseModel):
    detail: str
    current_version: int
    expected_version: int


# ── Goals ─────────────────────────────────────────────────────────────────


class ProjectGoalBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    category: str | None = Field(default=None, max_length=100)
    priority: str = Field(default="medium")
    owner_id: int | None = None
    status: str = Field(default="draft")
    start_date: datetime | None = None
    target_date: datetime | None = None
    linked_metric_ids: list[int] = Field(default_factory=list)
    linked_risk_ids: list[int] = Field(default_factory=list)


class ProjectGoalCreate(ProjectGoalBase):
    pass


class ProjectGoalUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    category: str | None = Field(default=None, max_length=100)
    priority: str | None = None
    owner_id: int | None = None
    status: str | None = None
    start_date: datetime | None = None
    target_date: datetime | None = None
    linked_metric_ids: list[int] | None = None
    linked_risk_ids: list[int] | None = None
    active: bool | None = None
    expected_version: int | None = None


class ProjectGoalRead(ProjectGoalBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    project_id: int
    active: bool
    position: int
    version: int
    created_at: datetime
    updated_at: datetime


# ── Metric targets ───────────────────────────────────────────────────────


class ProjectMetricTargetBase(BaseModel):
    target_type: str
    target_value: float | None = None
    lower_bound: float | None = None
    upper_bound: float | None = None
    comparison_operator: str | None = Field(default=None, max_length=10)
    warning_threshold: float | None = None
    critical_threshold: float | None = None
    baseline: float | None = None
    effective_start: datetime | None = None
    effective_end: datetime | None = None
    period: str | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=4000)
    status: str = Field(default="draft")


class ProjectMetricTargetCreate(ProjectMetricTargetBase):
    pass


class ProjectMetricTargetUpdate(BaseModel):
    target_type: str | None = None
    target_value: float | None = None
    lower_bound: float | None = None
    upper_bound: float | None = None
    comparison_operator: str | None = Field(default=None, max_length=10)
    warning_threshold: float | None = None
    critical_threshold: float | None = None
    baseline: float | None = None
    effective_start: datetime | None = None
    effective_end: datetime | None = None
    period: str | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=4000)
    status: str | None = None
    active: bool | None = None
    expected_version: int | None = None


class ProjectMetricTargetRead(ProjectMetricTargetBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    project_id: int
    metric_id: int
    active: bool
    position: int
    version: int
    created_at: datetime
    updated_at: datetime


# ── Metrics ───────────────────────────────────────────────────────────────


class ProjectMetricBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    business_definition: str | None = Field(default=None, max_length=4000)
    unit: str | None = Field(default=None, max_length=50)
    format: str | None = Field(default=None, max_length=50)
    directionality: str = Field(default="informational")
    aggregation: str = Field(default="latest")
    source_type: str | None = Field(default=None, max_length=50)
    source_query_id: int | None = None
    source_mapping: dict | None = None
    expression: str | None = Field(default=None, max_length=4000)
    success_criterion_id: int | None = None
    source_match_status: str | None = Field(default=None, max_length=20)
    latest_value: float | None = None
    latest_value_at: datetime | None = None
    owner_id: int | None = None
    cadence: str | None = Field(default=None, max_length=50)


class ProjectMetricCreate(ProjectMetricBase):
    targets: list[ProjectMetricTargetCreate] = Field(default_factory=list)


class ProjectMetricUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    business_definition: str | None = Field(default=None, max_length=4000)
    unit: str | None = Field(default=None, max_length=50)
    format: str | None = Field(default=None, max_length=50)
    directionality: str | None = None
    aggregation: str | None = None
    source_type: str | None = Field(default=None, max_length=50)
    source_query_id: int | None = None
    source_mapping: dict | None = None
    expression: str | None = Field(default=None, max_length=4000)
    success_criterion_id: int | None = None
    owner_id: int | None = None
    cadence: str | None = Field(default=None, max_length=50)
    active: bool | None = None
    expected_version: int | None = None


class ProjectMetricRead(ProjectMetricBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    project_id: int
    active: bool
    position: int
    version: int
    targets: list[ProjectMetricTargetRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @field_validator("targets", mode="before")
    @classmethod
    def _filter_active_targets(cls, v: list) -> list:
        return [item for item in v if getattr(item, "active", True)]


# ── Risks ─────────────────────────────────────────────────────────────────


class ProjectRiskBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    category: str | None = Field(default=None, max_length=100)
    likelihood: str | None = Field(default=None, max_length=20)
    impact: str | None = Field(default=None, max_length=20)
    severity: str | None = Field(default=None, max_length=20)
    rating_matrix_version: int | None = None
    owner_id: int | None = None
    mitigation: str | None = Field(default=None, max_length=4000)
    contingency: str | None = Field(default=None, max_length=4000)
    status: str = Field(default="open")
    review_date: datetime | None = None
    source_reference: str | None = Field(default=None, max_length=4000)
    linked_goal_ids: list[int] = Field(default_factory=list)
    linked_metric_ids: list[int] = Field(default_factory=list)


class ProjectRiskCreate(ProjectRiskBase):
    pass


class ProjectRiskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    category: str | None = Field(default=None, max_length=100)
    likelihood: str | None = Field(default=None, max_length=20)
    impact: str | None = Field(default=None, max_length=20)
    severity: str | None = Field(default=None, max_length=20)
    owner_id: int | None = None
    mitigation: str | None = Field(default=None, max_length=4000)
    contingency: str | None = Field(default=None, max_length=4000)
    status: str | None = None
    review_date: datetime | None = None
    source_reference: str | None = Field(default=None, max_length=4000)
    linked_goal_ids: list[int] | None = None
    linked_metric_ids: list[int] | None = None
    active: bool | None = None
    expected_version: int | None = None


class ProjectRiskRead(ProjectRiskBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    project_id: int
    active: bool
    position: int
    version: int
    created_at: datetime
    updated_at: datetime


# ── Full context response ─────────────────────────────────────────────────


class ProjectContextPermissions(BaseModel):
    can_edit: bool
    can_archive: bool


class ProjectContextRead(BaseModel):
    settings: ProjectBusinessContextRead | None = None
    goals: list[ProjectGoalRead] = Field(default_factory=list)
    metrics: list[ProjectMetricRead] = Field(default_factory=list)
    risks: list[ProjectRiskRead] = Field(default_factory=list)
    permissions: ProjectContextPermissions
    version: int = 0
    last_updated_at: datetime | None = None


# ── Reorder ─────────────────────────────────────────────────────────────────


class ReorderRequest(BaseModel):
    ids: list[int] = Field(min_length=1)
    expected_version: int | None = None


# ── Audit ───────────────────────────────────────────────────────────────────


class ProjectContextAuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    project_id: int
    actor_user_id: int | None
    actor_type: str
    event_type: str
    entity_type: str
    entity_id: int | None
    previous_value: dict | None
    new_value: dict | None
    version: int | None
    created_at: datetime


class ProjectContextAuditList(BaseModel):
    items: list[ProjectContextAuditEventRead]


class KpiSourceMatchJobCreate(BaseModel):
    expected_version: int | None = None


class KpiSourceMatchJobRead(BaseModel):
    ok: bool
    job_id: str
    message: str
