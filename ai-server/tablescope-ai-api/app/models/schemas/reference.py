"""Schemas for reference-library summarization and suggestion."""

from pydantic import BaseModel, Field

from .common import AIBaseRequest


class ReferenceSummarizeRequest(AIBaseRequest):
    """Summarize a reference-library document for AI grounding context."""
    document_id: int = 0
    title: str = ""
    issuing_body: str = ""
    domain_tag: str = ""
    extracted_text: str = ""


class ReferenceSummarizeResponse(BaseModel):
    summary: str = ""
    request_id: str = ""
    model_used: str = ""


class ReferenceSuggestRequest(AIBaseRequest):
    """Suggest relevant Industry reference domains for a project's signals."""
    data_source_types: list[str] = Field(default_factory=list)
    table_names: list[str] = Field(default_factory=list)
    document_types: list[str] = Field(default_factory=list)
    recent_query_topics: list[str] = Field(default_factory=list)
    candidate_domains: list[str] = Field(default_factory=list)


class ReferenceSuggestResponse(BaseModel):
    suggestions: list[dict] = Field(default_factory=list)
    request_id: str = ""
    model_used: str = ""
