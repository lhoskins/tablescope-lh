"""Schemas for proactive AI grounding evidence."""

from datetime import datetime
from typing import Any

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

    def manifest(self) -> dict[str, Any]:
        """Compact manifest for persistence and the insight-card UI."""
        return {
            "question": self.question,
            "passageCount": len(self.passages),
            "kgNodeCount": len(self.kg_nodes),
            "kpiCount": len(self.kpis),
            "insightSnapshotCount": len(self.insight_snapshots),
            "networkConnectionCount": len(self.network_connections),
            "referenceDocumentCount": len(self.reference_documents),
            "retrievedAt": self.retrieved_at.isoformat(),
            "kgVersionId": self.kg_version_id,
            "passages": [
                {
                    "documentId": p.document_id,
                    "chunkIndex": p.chunk_index,
                    "title": p.title,
                    "sourceType": p.source_type,
                    "tier": p.tier,
                    "retrievalMethod": p.retrieval_method,
                    "retrievalScore": p.retrieval_score,
                }
                for p in self.passages
            ],
            "kgNodes": [
                {"id": n.id, "nodeType": n.node_type, "title": n.title}
                for n in self.kg_nodes
            ],
            "kpis": [
                {"kpiKey": k.kpi_key, "displayName": k.display_name}
                for k in self.kpis
            ],
            "insightSnapshots": [
                {"insightId": s.insight_id, "title": s.title, "score": s.retrieval_score}
                for s in self.insight_snapshots
            ],
            "networkConnections": [
                {"id": c.id, "name": c.name} for c in self.network_connections
            ],
            "referenceDocuments": [
                {"id": d.id, "title": d.title, "score": d.retrieval_score}
                for d in self.reference_documents
            ],
        }
