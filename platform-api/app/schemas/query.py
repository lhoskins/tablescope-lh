"""Query request / response schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    projectId: int
    tableName: str
    columnName: str | None = None
    value: str | None = None
    limit: int = Field(default=1000, ge=1, le=10_000)


class QueryResponse(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    drilldownUsed: bool
    targetTable: str | None = None
    targetColumn: str | None = None
