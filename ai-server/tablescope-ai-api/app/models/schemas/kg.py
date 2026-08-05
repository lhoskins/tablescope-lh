"""Schemas for Knowledge-Graph insight cards."""

from pydantic import BaseModel, Field

from .common import AIBaseRequest


class KnowledgeGraphInsightRequest(AIBaseRequest):
    """Generate Knowledge-Graph business-insight cards for a selected node.

    The platform supplies the deterministic node-centric neighborhood (the
    selected center node and its connected nodes/edges); the model reasons over
    that neighborhood — grounded ONLY in the supplied nodes — and returns
    AI-Home-style insight cards specific to the graph's related data sources.
    """
    lens: str = "insight-first"
    center: dict = Field(default_factory=dict)  # {graph_key, type, label, summary, display_group}
    # Connected nodes: [{graph_key, type, label, display_group, relationship,
    # confidence, direction}]
    neighbors: list[dict] = Field(default_factory=list)
    documents: list[dict] = Field(default_factory=list)  # [{title, summary, source}]
    kpis: list[str] = Field(default_factory=list)
    max_cards: int = 8


class KnowledgeGraphCard(BaseModel):
    id: str = ""
    # business_insight | opportunity | risk | warning | gap | recommendation
    category: str = "business_insight"
    # critical | urgent | warning | watch | opportunity | info
    severity: str = "info"
    title: str = ""
    summary: str = ""
    businessQuestion: str = ""
    businessImpact: str = ""
    confidence: float = 0.0
    recommendedAction: str = ""
    # graph_keys of supporting neighbor nodes (must be from the supplied set)
    evidenceKeys: list[str] = Field(default_factory=list)
    sourceDocuments: list[str] = Field(default_factory=list)
    supportedKpis: list[str] = Field(default_factory=list)


class KnowledgeGraphInsightResponse(BaseModel):
    cards: list[KnowledgeGraphCard] = Field(default_factory=list)
    request_id: str = ""
    model_used: str = ""
