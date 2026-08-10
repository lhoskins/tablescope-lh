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


class GroundingInsightSnapshot(BaseModel):
    """A precomputed insight card from Business or Project Insight snapshots."""

    insight_id: str = ""
    project_id: int | None = None
    project_name: str = ""
    title: str = ""
    summary: str = ""
    card_type: str = ""
    sql: str = ""
    result_preview: str = ""
    chart_type: str = ""
    series: list[str] = Field(default_factory=list)
    trend: str = ""
    retrieval_score: float = 0.0


class GroundingNetworkConnection(BaseModel):
    """An approved SMB/UNC network file connection available to the project."""

    id: int | None = None
    name: str = ""
    protocol: str = ""
    host: str = ""
    share_name: str = ""
    approved_root_path: str = ""
    domain: str | None = None
    enabled: bool = True


class GroundingReferenceDocument(BaseModel):
    """A Reference Library document profiled by AI, surfaced for grounding."""

    id: int | None = None
    title: str = ""
    ai_summary: str = ""
    tier: str = ""
    domain_tag: str | None = None
    source_url: str | None = None
    retrieval_score: float = 0.0


class GroundingEvidence(BaseModel):
    """Bundle of evidence retrieved to ground an AI answer."""

    question: str = ""
    passages: list[GroundingPassage] = Field(default_factory=list)
    kg_nodes: list[GroundingKGNode] = Field(default_factory=list)
    kpis: list[GroundingKPI] = Field(default_factory=list)
    insight_snapshots: list[GroundingInsightSnapshot] = Field(default_factory=list)
    network_connections: list[GroundingNetworkConnection] = Field(default_factory=list)
    reference_documents: list[GroundingReferenceDocument] = Field(default_factory=list)
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
