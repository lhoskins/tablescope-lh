"""Schemas for document-family summarization."""

from pydantic import BaseModel, Field

from .common import AIBaseRequest


class FamilySummarizeRequest(AIBaseRequest):
    """Summarize a document family from its active members."""
    family_name: str
    family_type: str = ""
    business_domain: str = ""
    member_documents: list[dict] = Field(default_factory=list)
    member_datasources: list[dict] = Field(default_factory=list)
    member_kpis: list[str] = Field(default_factory=list)
    member_entities: list[str] = Field(default_factory=list)
    relationships: list[dict] = Field(default_factory=list)


class FamilySummarizeResponse(BaseModel):
    summary: str = ""
    primary_purpose: str = ""
    supported_kpis: list[str] = Field(default_factory=list)
    related_processes: list[str] = Field(default_factory=list)
    suggested_dashboards: list[str] = Field(default_factory=list)
    missing_documents: list[str] = Field(default_factory=list)
    suggested_questions: list[str] = Field(default_factory=list)
    request_id: str = ""
    model_used: str = ""
