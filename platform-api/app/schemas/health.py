"""Health response schemas."""

from __future__ import annotations

from pydantic import BaseModel


class ComponentHealth(BaseModel):
    name: str
    status: str
    detail: str | None = None


class HealthStatus(BaseModel):
    status: str
    version: str
    components: list[ComponentHealth] = []
