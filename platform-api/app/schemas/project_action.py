"""Project Action schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProjectActionSubtaskBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = None
    status: str = "not_started"
    percent_complete: int = Field(default=0, ge=0, le=100)
    owner_user_id: int | None = None
    due_date: datetime | None = None
    position: int = 0
    is_required: bool = True
    effort_points: int | None = Field(default=None, ge=1, le=10)

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v: str) -> str:
        allowed = {"not_started", "in_progress", "blocked", "completed", "cancelled"}
        if v not in allowed:
            raise ValueError(f"status must be one of {allowed}")
        return v


class ProjectActionSubtaskCreate(ProjectActionSubtaskBase):
    pass


class ProjectActionSubtaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    status: str | None = None
    percent_complete: int | None = Field(default=None, ge=0, le=100)
    owner_user_id: int | None = None
    due_date: datetime | None = None
    position: int | None = None
    is_required: bool | None = None
    effort_points: int | None = Field(default=None, ge=1, le=10)
    archived_at: datetime | None = None
    expected_version: int | None = None

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v: str | None) -> str | None:
        if v is None:
            return v
        allowed = {"not_started", "in_progress", "blocked", "completed", "cancelled"}
        if v not in allowed:
            raise ValueError(f"status must be one of {allowed}")
        return v

    @field_validator("effort_points")
    @classmethod
    def _validate_effort(cls, v: int | None) -> int | None:
        if v is None:
            return v
        if v < 1 or v > 10:
            raise ValueError("effort_points must be between 1 and 10")
        return v


class ProjectActionSubtaskOut(ProjectActionSubtaskBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    action_id: int
    tenant_id: int
    project_id: int
    created_by_user_id: int | None = None
    updated_by_user_id: int | None = None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None
    completed_at: datetime | None = None
    lock_version: int


class ProjectActionBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = None
    status: str = "not_started"
    priority: str = "medium"
    owner_user_id: int | None = None
    due_date: datetime | None = None
    source_type: str = "insight"
    source_insight_id: str | None = None
    source_insight_type: str | None = None
    source_insight_title: str | None = None
    source_insight_snapshot: dict[str, Any] | None = None

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v: str) -> str:
        allowed = {"not_started", "in_progress", "blocked", "completed", "cancelled"}
        if v not in allowed:
            raise ValueError(f"status must be one of {allowed}")
        return v

    @field_validator("priority")
    @classmethod
    def _validate_priority(cls, v: str) -> str:
        allowed = {"low", "medium", "high", "critical"}
        if v not in allowed:
            raise ValueError(f"priority must be one of {allowed}")
        return v


class ProjectActionCreate(ProjectActionBase):
    initial_subtasks: list[ProjectActionSubtaskCreate] = Field(default_factory=list)
    idempotency_key: str | None = None


class ProjectActionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    status: str | None = None
    priority: str | None = None
    owner_user_id: int | None = None
    due_date: datetime | None = None
    percent_complete: int | None = Field(default=None, ge=0, le=100)
    archived_at: datetime | None = None
    expected_version: int | None = None

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v: str | None) -> str | None:
        if v is None:
            return v
        allowed = {"not_started", "in_progress", "blocked", "completed", "cancelled"}
        if v not in allowed:
            raise ValueError(f"status must be one of {allowed}")
        return v

    @field_validator("priority")
    @classmethod
    def _validate_priority(cls, v: str | None) -> str | None:
        if v is None:
            return v
        allowed = {"low", "medium", "high", "critical"}
        if v not in allowed:
            raise ValueError(f"priority must be one of {allowed}")
        return v


class ProjectActionOut(ProjectActionBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    project_id: int
    percent_complete: int
    source_insight_fingerprint: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_by_user_id: int | None = None
    updated_by_user_id: int | None = None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None
    lock_version: int
    subtasks: list[ProjectActionSubtaskOut] = Field(default_factory=list)


class ProjectActionSummaryOwner(BaseModel):
    user_id: int | None = None
    display_name: str | None = None


class ProjectActionListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None = None
    status: str
    priority: str
    owner_user_id: int | None = None
    owner_name: str | None = None
    due_date: datetime | None = None
    percent_complete: int
    source_type: str = "insight"
    source_insight_id: str | None = None
    source_insight_fingerprint: str | None = None
    source_insight_type: str | None = None
    source_insight_title: str | None = None
    source_insight_snapshot: dict[str, Any] | None = None
    risk_impact: str | None = None
    active_subtasks: int = 0
    total_subtasks: int = 0
    completed_required_subtasks: int = 0
    required_subtasks: int = 0
    comment_count: int = 0
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime
    archived_at: datetime | None = None
    lock_version: int


class ProjectActionGroupSummary(BaseModel):
    group: str
    label: str
    count: int
    overdue_count: int = 0
    avg_progress: int = 0


class ProjectActionBoardSummary(BaseModel):
    active: int = 0
    overdue: int = 0
    avg_progress: int = 0
    risk_mitigations_completed: int = 0
    groups: list[ProjectActionGroupSummary] = Field(default_factory=list)


class ProjectActionListResponse(BaseModel):
    items: list[ProjectActionListItem] = Field(default_factory=list)
    total: int = 0
    summary: ProjectActionBoardSummary = Field(
        default_factory=ProjectActionBoardSummary,
    )


class ProjectActionCountForInsightRequest(BaseModel):
    source_insight_id: str | None = None
    source_insight_type: str | None = None
    source_insight_title: str | None = None
    source_insight_snapshot: dict[str, Any] | None = None


class ProjectActionCountForInsightResponse(BaseModel):
    count: int
    action_ids: list[int] = Field(default_factory=list)


class ProjectActionBulkItem(BaseModel):
    action_id: int
    expected_version: int


class ProjectActionBulkUpdate(BaseModel):
    action_ids: list[int]
    expected_versions: dict[int, int] = Field(default_factory=dict)
    status: str | None = None
    priority: str | None = None
    owner_user_id: int | None = None
    due_date: datetime | None = None

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v: str | None) -> str | None:
        if v is None:
            return v
        allowed = {"not_started", "in_progress", "blocked", "completed", "cancelled"}
        if v not in allowed:
            raise ValueError(f"status must be one of {allowed}")
        return v

    @field_validator("priority")
    @classmethod
    def _validate_priority(cls, v: str | None) -> str | None:
        if v is None:
            return v
        allowed = {"low", "medium", "high", "critical"}
        if v not in allowed:
            raise ValueError(f"priority must be one of {allowed}")
        return v


class ProjectActionBulkResultItem(BaseModel):
    action_id: int
    success: bool
    lock_version: int | None = None
    error: str | None = None


class ProjectActionBulkResponse(BaseModel):
    results: list[ProjectActionBulkResultItem]


class ProjectActionCommentCreate(BaseModel):
    body: str = Field(..., min_length=1, max_length=5000)


class ProjectActionCommentUpdate(BaseModel):
    body: str = Field(..., min_length=1, max_length=5000)


class ProjectActionCommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    project_id: int
    action_id: int
    author_user_id: int | None = None
    author_name: str | None = None
    body: str
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None
