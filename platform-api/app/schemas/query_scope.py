"""Query scope (drill-down) schemas — keyed by saved-query id."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class QueryScopeCreate(BaseModel):
    query_id: int
    source_field: str
    target_query_id: int
    target_field: str


class QueryScopeUpdate(BaseModel):
    target_query_id: int
    target_field: str


class QueryScopeRead(BaseModel):
    id: int
    tenant_id: int
    project_id: int
    query_id: int
    source_field: str
    target_query_id: int
    target_field: str


class QueryScopeFilterRequest(BaseModel):
    scope_id: int
    value: Any
    limit: int = 1000


class QueryScopeFilterResponse(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    target_query_id: int
    target_query_name: str
    target_field: str
