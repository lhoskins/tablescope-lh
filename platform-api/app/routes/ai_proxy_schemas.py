"""Request/response models shared by the AI proxy feature routers."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AIAskRequest(BaseModel):
    project_id: int
    question: str
    scope: str = "project"
    include_query_history: bool = True
    include_dashboard_context: bool = True
    history: list[dict[str, Any]] = Field(default_factory=list)


class AIGenerateSQLRequest(BaseModel):
    project_id: int
    prompt: str
    allowed_tables: list[str] = []


class AIGenerateRelationshipsRequest(BaseModel):
    project_id: int


class AISuggestDashboardRequest(BaseModel):
    project_id: int


class AIIndexDocumentRequest(BaseModel):
    project_id: int
    document_id: int
    source_type: str
    source_id: int
    content: str = ""
    visibility: str = "shared_project"


class AISaveQueryRequest(BaseModel):
    """Save AI-generated SQL as a project query."""
    project_id: int
    name: str
    description: str | None = None
    sql_text: str


class AIGenerateAndSaveQueryRequest(BaseModel):
    """Generate SQL from prompt and save as a project query."""
    project_id: int
    prompt: str
    name: str | None = None
    description: str | None = None
    allowed_tables: list[str] = []


class AIGenerateAndSaveDashboardRequest(BaseModel):
    """Generate a full dashboard with widgets from a prompt and save."""
    project_id: int
    prompt: str | None = None
    name: str | None = None
    description: str | None = None


class AICardContext(BaseModel):
    """Source context carried from a Business/Project Insight card.

    Lets the Project Semantic Source Resolver prefer the exact authorized
    source a card's finding was grounded in, instead of re-inferring it from
    the plain sentence.
    """
    insight_type: str | None = None
    source_tables: list[str] = Field(default_factory=list)
    source_columns: list[str] = Field(default_factory=list)
    metric: str | None = None
    period_column: str | None = None
    #: The card's own text, so a follow-up is answered about *this* finding.
    title: str | None = None
    summary: str | None = None
    #: The query the finding was computed from. A question asked from a card
    #: ("what is driving this?") should extend the query that produced it —
    #: without this the generator writes a fresh query and can answer about
    #: subtly different rows than the card the user is looking at.
    base_sql: str | None = None
    #: Provenance of the analysis being asked about, when the question comes
    #: from a specific diagnostic step rather than the card as a whole.
    analytical_method: dict[str, Any] | None = None

    def to_resolver_context(self) -> dict[str, Any]:
        return {
            "insightType": self.insight_type,
            "sourceTables": self.source_tables,
            "sourceColumns": self.source_columns,
            "metric": self.metric,
            "periodColumn": self.period_column,
        }

    def to_card(self) -> dict[str, Any]:
        """Shape :mod:`ask_pipeline` expects for grounding a follow-up."""
        return {
            "title": self.title,
            "summary": self.summary,
            "sql": self.base_sql,
            "insightType": self.insight_type,
            "metric": self.metric,
            "analyticalMethod": self.analytical_method or {},
            "sources": {"tables": list(self.source_tables)},
        }


class AIAskAndRunRequest(BaseModel):
    """Generate SQL for a natural-language question, execute it, return rows.

    Powers the inline AI Question modal: the user clicks an AI-generated
    question and sees the answer (results) directly instead of being routed to
    the AI Assistant chat.
    """
    project_id: int
    question: str
    source: str | None = None
    card_context: AICardContext | None = None
    max_rows: int = 200


class AIGenerateQueryPreviewRequest(BaseModel):
    """Generate + execute a recommended query and return a renderable preview.

    Powers the Recommended Queries "Generate" button: generates SQL from the
    recommendation's business question, executes it, and returns rows so the
    user can preview before saving.
    """
    project_id: int
    question: str
    title: str | None = None
    description: str | None = None
    card_context: AICardContext | None = None
    max_rows: int = 200


class AISuggestDashboardsRequest(BaseModel):
    """Request several dashboard plan suggestions for a project (no save)."""
    project_id: int
    prompt: str | None = None
    audience: str | None = None
    desired_count: int = 3


class AISuggestionWidget(BaseModel):
    """A single widget carried in a dashboard suggestion's savePayload.

    Previews now carry executable ``sql`` (plus label/value columns), so Save can
    persist the exact widgets the user previewed instead of re-deriving a plan.
    """
    title: str = ""
    chartType: str = ""
    businessQuestion: str = ""
    sql: str = ""
    labelColumn: str = ""
    valueColumn: str = ""
    status: str = ""


class AISuggestionPayload(BaseModel):
    """The selected suggestion the user chose to persist (its savePayload)."""
    title: str = ""
    description: str = ""
    businessPurpose: str = ""
    audience: str = ""
    prompt: str = ""
    widgets: list[AISuggestionWidget] = []
    kpis: list[str] = []
    dataSources: list[str] = []


class AISaveDashboardSuggestionRequest(BaseModel):
    """Persist a previewed dashboard suggestion (strict save validation)."""
    project_id: int
    suggestionId: str | None = None
    suggestion: AISuggestionPayload


class AICreateScopeRequest(BaseModel):
    """Create a single scope from an AI suggestion."""
    sourceTable: str
    sourceColumn: str
    targetTable: str
    targetColumn: str


class AIPermissionsResponse(BaseModel):
    tenant_id: int
    user_id: int
    project_id: int
    is_member: bool
    is_owner: bool
    project_visibility: str
    datasources: list[dict[str, Any]]
    saved_queries: list[dict[str, Any]]
    dashboards: list[dict[str, Any]]
    query_scopes: list[dict[str, Any]] = []
    accepted_tags: list[dict[str, Any]] = []
    accepted_kpis: list[dict[str, Any]] = []
    enabled_reference_tags: list[dict[str, Any]] = []
    enabled_reference_kpis: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []
    graph_nodes: list[dict[str, Any]] = []
    graph_edges: list[dict[str, Any]] = []
    document_families: list[dict[str, Any]] = []


class RoutePromptRequest(BaseModel):
    prompt: str
    project_id: int | None = None


class RoutePromptResponse(BaseModel):
    route: str
    prefilled: str
