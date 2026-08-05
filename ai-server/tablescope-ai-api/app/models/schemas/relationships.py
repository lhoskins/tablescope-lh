"""Schemas for table-relationship generation."""

from pydantic import BaseModel

from .common import AIBaseRequest


class GenerateRelationshipsRequest(AIBaseRequest):
    pass


class RelationshipSuggestion(BaseModel):
    left_table: str
    left_column: str
    right_table: str
    right_column: str
    confidence: float
    reason: str


class GenerateRelationshipsResponse(BaseModel):
    relationships: list[RelationshipSuggestion]
    request_id: str
    model_used: str
