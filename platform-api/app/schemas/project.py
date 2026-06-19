"""Project schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    type: str | None = None
    is_shared: bool = False


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    type: str | None = None
    is_shared: bool | None = None
    scoping_enabled: bool | None = None


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    owner_id: int | None
    name: str
    description: str | None
    type: str | None
    is_shared: bool
    scoping_enabled: bool
    created_at: datetime
    updated_at: datetime


class ProjectSummaryRead(BaseModel):
    """Project plus rollup counts and AI status for list/home cards."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    is_shared: bool
    updated_at: datetime
    document_count: int = 0
    query_count: int = 0
    dashboard_count: int = 0
    member_count: int = 0
    data_source_count: int = 0
    ai_status: str = "idle"


class ProjectMemberRead(BaseModel):
    project_id: int
    user_id: int
    role: str
    is_active: bool = True
    email: str = ""
    display_name: str | None = None


class AddableUserRead(BaseModel):
    """A tenant user eligible to be added to a project (member picker)."""

    user_id: int
    email: str
    display_name: str | None = None
    role: str = "viewer"


# ── Saved Query schemas ──────────────────────────────────────────────


class SavedQueryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    left_datasource: str | None = None
    right_datasource: str | None = None
    join_type: str | None = None
    left_column: str | None = None
    right_column: str | None = None
    sql_text: str | None = None
    ai_generated: bool = False
    is_shared: bool = False


class SavedQueryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    left_datasource: str | None = None
    right_datasource: str | None = None
    join_type: str | None = None
    left_column: str | None = None
    right_column: str | None = None
    sql_text: str | None = None
    ai_generated: bool | None = None
    is_shared: bool | None = None


class SavedQueryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    owner_id: int | None
    name: str
    description: str | None
    left_datasource: str | None
    right_datasource: str | None
    join_type: str | None
    left_column: str | None
    right_column: str | None
    sql_text: str | None
    ai_generated: bool = False
    is_shared: bool = False
    run_count: int = 0
    last_run_at: datetime | None = None
    avg_runtime_ms: int | None = None
    created_at: datetime
    updated_at: datetime
