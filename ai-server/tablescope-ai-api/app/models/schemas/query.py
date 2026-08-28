"""Schemas for SQL generation and saved-query matching."""

from typing import Any

from pydantic import BaseModel, Field

from .common import AIBaseRequest, QueryInfo
from .grounding import GroundingEvidence


class SourceCatalogEntry(BaseModel):
    """A project source the AI may use, with its columns + description."""
    name: str
    columns: list[str] = Field(default_factory=list)
    description: str | None = None
    kind: str = "table"  # "table" (data source view) or "query" (saved query)
    # Row count, date range, and a few categorical columns' distinct values,
    # e.g. "40 rows; \"Date\" range 2026-06-13 to 2026-06-24 (text); \"System\"
    # values: ERP, FileServer, MES, PLM" -- read from the source's existing
    # upload-time profile so the model never invents a column, guesses a date
    # window the data can't satisfy, or assumes a trend where there's only one
    # period.
    profile_summary: str | None = None


class GenerateSQLRequest(AIBaseRequest):
    prompt: str
    allowed_tables: list[str] = Field(default_factory=list)
    source_catalog: list[SourceCatalogEntry] = Field(default_factory=list)
    # Resolved by the platform-api Project Semantic Source Resolver before this
    # call: the authorized source(s) and columns the request most likely maps
    # to. The generator must prefer these unless they cannot answer the prompt.
    preferred_sources: list[str] = Field(default_factory=list)
    relevant_columns: list[str] = Field(default_factory=list)
    # Compact, AI-safe Knowledge Graph summary (risks/gaps/measured KPIs/docs);
    # steers SQL toward validated business questions, never Reference Library.
    knowledge_graph_context: dict[str, Any] = Field(default_factory=dict)
    # Proactive hybrid retrieval evidence (document passages, KG nodes, KPIs).
    grounding_evidence: GroundingEvidence | None = None
    # Verified join candidates discovered by the platform (same shape as the
    # dashboard pipeline's relationship_hints). Empty leaves single-table
    # behaviour unchanged.
    relationship_hints: list[dict] = Field(default_factory=list)


class MatchQueryRequest(AIBaseRequest):
    """Find an existing saved query functionally equivalent to a candidate."""
    candidate_title: str = ""
    candidate_sql: str
    existing_queries: list[QueryInfo] = Field(default_factory=list)


class MatchQueryResponse(BaseModel):
    """Result of a query-equivalence check. match_id is None when none match."""
    match_id: int | None = None
    request_id: str
    model_used: str


class SelectedSource(BaseModel):
    """A project source the AI chose, plus why it matched the request."""
    name: str
    reason: str = ""


class SelectedField(BaseModel):
    source: str
    field: str
    reason: str = ""


class GenerateSQLResponse(BaseModel):
    sql: str
    explanation: str
    allowed_tables_used: list[str]
    request_id: str
    model_used: str
    selected_sources: list[SelectedSource] = Field(default_factory=list)
    selected_fields: list[SelectedField] = Field(default_factory=list)
    repaired: bool = False
    # True when Knowledge Graph context was folded into the generation prompt,
    # so the platform can persist query metadata (knowledgeGraphContextUsed).
    knowledge_graph_context_used: bool = False
    # Manifest of evidence used to ground the generation (when provided).
    grounding_manifest: dict[str, Any] | None = None
