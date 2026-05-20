"""Tenant + user schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class TenantCreate(BaseModel):
    slug: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9-]+$")
    name: str = Field(min_length=1, max_length=255)
    external_id: str | None = None
    root_user_email: EmailStr | None = None
    root_user_name: str | None = None
    root_user_password: str | None = None


class TenantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str
    external_id: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserCreate(BaseModel):
    email: EmailStr
    display_name: str | None = None
    role: str = "viewer"
    external_id: str | None = None
    password: str | None = None


class UserUpdate(BaseModel):
    display_name: str | None = None
    role: str | None = None
    is_active: bool | None = None
    password: str | None = None


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    email: str
    display_name: str | None
    role: str
    external_id: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
