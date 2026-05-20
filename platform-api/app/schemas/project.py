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
    model_config = ConfigDict(from_attributes=True)

    project_id: int
    user_id: int
    role: str
