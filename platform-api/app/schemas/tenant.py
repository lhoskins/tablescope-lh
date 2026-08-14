"""Tenant + user schemas."""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TenantCreate(BaseModel):
    slug: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9-]+$")
    name: str = Field(min_length=1, max_length=255)
    external_id: str | None = None
    root_user_email: str | None = None
    root_user_name: str | None = None
    root_user_password: str | None = None


class TenantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str
    external_id: str | None
    is_active: bool
    enforce_2fa: bool = False
    voice_input_enabled: bool = False
    logo_url: str | None = None
    created_at: datetime
    updated_at: datetime


class CompanyLogoRead(BaseModel):
    """The calling tenant's company logo URL (or null when unset)."""

    logo_url: str | None = None


class TenantDeleteResponse(BaseModel):
    tenant_id: int
    slug: str
    deleted_rows: dict[str, int]
    vdbs_undeployed: int
    folders_removed: bool


_LOOSE_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class UserCreate(BaseModel):
    email: str
    display_name: str | None = None
    role: str = "member"
    external_id: str | None = None
    password: str | None = None

    @field_validator("email")
    @classmethod
    def _validate_email(cls, v: str) -> str:
        if not _LOOSE_EMAIL_RE.match(v):
            raise ValueError("Not a valid email address")
        return v.strip().lower()


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
    is_super_admin: bool = False
    created_at: datetime
    updated_at: datetime


class AllowedDomainRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    domain: str
    is_active: bool


class AllowedDomainsResponse(BaseModel):
    enabled: bool
    domains: list[AllowedDomainRead]


class AllowedDomainsSettingsUpdate(BaseModel):
    enabled: bool


class Enforce2faSettingsUpdate(BaseModel):
    enabled: bool


class Enforce2faSettingsResponse(BaseModel):
    enabled: bool


class TenantSettingsRead(BaseModel):
    """Safe tenant-facing settings: no users, VDBs, or infrastructure metadata."""

    id: int
    name: str
    slug: str
    is_active: bool
    enforce_2fa: bool
    allowed_domains_enabled: bool
    voice_input_enabled: bool = False
    logo_url: str | None = None
    login_url: str | None = None
    created_at: datetime
    updated_at: datetime


class TenantReprocessResponse(BaseModel):
    tenant_id: int
    status: str
    total_projects: int
    projects_queued: int
    projects_skipped: int
    job_ids: list[str]
    force: bool


class AllowedDomainCreate(BaseModel):
    domain: str
