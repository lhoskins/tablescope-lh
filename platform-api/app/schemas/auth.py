"""Auth request / response schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AuthExchangeRequest(BaseModel):
    """Exchange a Clerk/Supabase JWT for a first-party access token."""

    provider: Literal["clerk", "supabase"]
    token: str = Field(min_length=10)
    tenant_slug: str | None = None


class DirectLoginRequest(BaseModel):
    """Email/password login without an external auth provider."""

    email: str = Field(min_length=1)
    password: str = Field(min_length=1)
    tenant_slug: str | None = None


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    tenant_id: int
    user_id: int
    role: str
    is_super_admin: bool = False
    tenant_slug: str | None = None


class CurrentUserResponse(BaseModel):
    """Identity of the authenticated caller, for the app shell."""

    user_id: int
    email: str
    display_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    role: str
    is_super_admin: bool = False
    tenant_id: int
    tenant_name: str
    tenant_slug: str | None = None
    avatar_url: str | None = None
