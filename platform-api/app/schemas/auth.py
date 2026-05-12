"""Auth request / response schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AuthExchangeRequest(BaseModel):
    """Exchange a Clerk/Supabase JWT for a first-party access token."""

    provider: Literal["clerk", "supabase"]
    token: str = Field(min_length=10)
    tenant_slug: str | None = None


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    tenant_id: int
    user_id: int
    role: str
