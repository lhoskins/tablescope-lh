"""Schemas for drill-down scope analysis."""

from pydantic import BaseModel

from .common import AIBaseRequest, QueryInfo


class AnalyzeScopesRequest(AIBaseRequest):
    """Request to analyze queries and suggest drill-down scopes."""
    queries: list[QueryInfo]


class ScopeSuggestion(BaseModel):
    source_query_id: int
    source_query_name: str
    source_field: str
    target_query_id: int
    target_query_name: str
    target_field: str
    confidence: float
    reason: str


class AnalyzeScopesResponse(BaseModel):
    scopes: list[ScopeSuggestion]
    request_id: str
    model_used: str
