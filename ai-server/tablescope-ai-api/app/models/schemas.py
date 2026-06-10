"""Pydantic schemas for AI API requests and responses."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class AIBaseRequest(BaseModel):
    """Base request — every AI call requires tenant/user/project context."""
    tenant_id: int
    user_id: int
    project_id: int
    signature: str = ""
    timestamp: float = 0.0


class AskRequest(AIBaseRequest):
    question: str
    scope: str = "project"  # project | personal | shared_project
    include_query_history: bool = True
    include_dashboard_context: bool = True


class IndexDocumentRequest(AIBaseRequest):
    document_id: int
    source_type: str  # uploaded_file | query_result | dashboard | scope
    source_id: int
    file_path: str = ""
    content: str = ""
    visibility: str = "shared_project"


class GenerateRelationshipsRequest(AIBaseRequest):
    pass


class GenerateSQLRequest(AIBaseRequest):
    prompt: str
    allowed_tables: list[str] = Field(default_factory=list)


class SuggestDashboardRequest(AIBaseRequest):
    prompt: str = ""
    allowed_tables: list[str] = []


class QueryInfo(BaseModel):
    """Minimal query info for scope analysis."""
    id: int
    name: str
    sql: str


class AnalyzeFileRequest(BaseModel):
    """Request to analyze a file profile — no tenant context required."""
    prompt: str
    task: str = "file_analysis"
    response_format: str = "json"
    signature: str = ""
    timestamp: float = 0.0


class AnalyzeFileResponse(BaseModel):
    analysis: dict
    request_id: str
    model_used: str


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


class DocumentProfileRequest(BaseModel):
    """Request to profile an uploaded document."""
    tenant_id: int
    user_id: int
    project_id: int
    asset_id: int
    document_id: int | None = None
    filename: str
    asset_type: str
    content_type: str = ""
    text_preview: str
    chunks: list[dict] = []
    enabled_reference_tags: list[str] = []
    enabled_reference_kpis: list[str] = []
    signature: str = ""
    timestamp: float = 0.0


class DocumentProfileResponse(BaseModel):
    summary: str = ""
    document_type: str = ""
    business_domain: str = ""
    process_area: str = ""
    tags: list[dict] = []
    entities: list[dict] = []
    recommended_kpis: list[dict] = []
    relationship_hints: list[dict] = []
    data_quality_notes: list[str] = []
    suggested_questions: list[str] = []
    request_id: str = ""
    model_used: str = ""


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str
    ollama: str
    qdrant: str
    gpu: str


class AskResponse(BaseModel):
    answer: str
    model_used: str
    request_id: str
    context_summary: dict[str, Any] = Field(default_factory=dict)
    audit_id: int | None = None


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


class GenerateSQLResponse(BaseModel):
    sql: str
    explanation: str
    allowed_tables_used: list[str]
    request_id: str
    model_used: str


class DashboardWidgetSuggestion(BaseModel):
    type: str  # kpi | bar | line | pie | area | table
    title: str
    sql: str = ""
    x_column: str | None = ""
    y_column: str | None = ""
    aggregation: str | None = ""


class DashboardSuggestion(BaseModel):
    title: str
    widgets: list[DashboardWidgetSuggestion]


class SuggestDashboardResponse(BaseModel):
    suggestions: list[DashboardSuggestion]
    request_id: str
    model_used: str


# ---------------------------------------------------------------------------
# Vector / context schemas
# ---------------------------------------------------------------------------

class VectorPayload(BaseModel):
    """Security payload stored with every vector in Qdrant."""
    vector_id: str
    tenant_id: int
    project_id: int
    document_id: int | None = None
    chunk_id: str = ""
    chunk_index: int = 0
    visibility: str = "shared_project"
    owner_user_id: int | None = None
    allowed_user_ids: list[int] = Field(default_factory=list)
    allowed_group_ids: list[int] = Field(default_factory=list)
    source_type: str = ""
    source_id: int | None = None
    embedding_model: str = ""
    field_name: str = ""
    table_name: str = ""
    query_id: int | None = None
    dashboard_id: int | None = None
    scope_id: int | None = None
    content_hash: str = ""
    token_count: int = 0
    created_at: datetime | None = None


class ContextPackage(BaseModel):
    """The controlled context sent to the LLM — built by the context builder."""
    tenant_id: int
    user_id: int
    project_id: int
    allowed_context: dict[str, list[Any]] = Field(default_factory=lambda: {
        "metadata": [],
        "documents": [],
        "relationships": [],
        "queries": [],
        "dashboards": [],
        "memories": [],
    })
    retrieval_filters: dict[str, Any] = Field(default_factory=dict)
    audit_context_id: str = ""
