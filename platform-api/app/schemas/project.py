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


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    owner_id: int | None
    name: str
    description: str | None
    type: str | None
    is_shared: bool
    created_at: datetime
    updated_at: datetime


class ProjectMemberRead(BaseModel):
    project_id: int
    user_id: int
    role: str
    is_active: bool = True
    email: str = ""
    display_name: str | None = None


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


class SavedQueryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    left_datasource: str | None = None
    right_datasource: str | None = None
    join_type: str | None = None
    left_column: str | None = None
    right_column: str | None = None
    sql_text: str | None = None


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
    created_at: datetime
    updated_at: datetime
