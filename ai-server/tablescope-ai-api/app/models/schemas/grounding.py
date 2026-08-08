"""Schemas for proactive AI grounding evidence."""

from datetime import datetime

from pydantic import BaseModel, Field


class GroundingPassage(BaseModel):
    """A retrieved document passage used to ground an answer."""

    id: str | None = None
    document_id: int | None = None
    chunk_index: int | None = None
    title: str = ""
    text: str = ""
    tier: str = ""  # project, company, industry for reference docs
    source_type: str = ""  # project_asset or reference_library
    retrieval_score: float = 0.0
    retrieval_method: str = ""  # vector, lexical


class GroundingKGNode(BaseModel):
    """A knowledge-graph node selected as grounding evidence."""

    id: int | str | None = None
    node_type: str = ""
    title: str = ""
    summary: str = ""
    confidence: float = 0.0
    relevance_score: float = 0.0


class GroundingKPI(BaseModel):
    """A governed KPI matched to the question."""

    kpi_key: str = ""
    display_name: str = ""
    business_domain: str | None = None
    required_fields: list[str] = Field(default_factory=list)
    related_tags: list[str] = Field(default_factory=list)
    match_score: float = 0.0


class GroundingEvidence(BaseModel):
    """Bundle of evidence retrieved to ground an AI answer."""

    question: str = ""
    passages: list[GroundingPassage] = Field(default_factory=list)
    kg_nodes: list[GroundingKGNode] = Field(default_factory=list)
    kpis: list[GroundingKPI] = Field(default_factory=list)
    retrieved_at: datetime = Field(default_factory=datetime.utcnow)
    kg_version_id: int | None = None


class GroundingSearchRequest(BaseModel):
    """Request vector grounding search from the platform-api orchestrator."""

    tenant_id: int
    user_id: int
    project_id: int
    question: str
    scope: str = "project"
    limit: int = 12
    signature: str = ""
    timestamp: float = 0.0


class GroundingSearchResponse(BaseModel):
    """Vector search results returned to the platform-api orchestrator."""

    request_id: str = ""
    project_passages: list[GroundingPassage] = Field(default_factory=list)
    reference_passages: list[GroundingPassage] = Field(default_factory=list)
