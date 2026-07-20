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
    # Prior turns of the same conversation (oldest→newest), each
    # {"role": "user"|"assistant", "content": "..."}. Lets the model resolve
    # follow-up references ("explain more", "the second option").
    history: list[dict[str, Any]] = Field(default_factory=list)
    # Compact, AI-safe Knowledge Graph summary; grounds prose answers in the
    # same measured risks/gaps/KPIs used by dashboard and query generation.
    knowledge_graph_context: dict[str, Any] = Field(default_factory=dict)


class IndexDocumentRequest(AIBaseRequest):
    document_id: int
    source_type: str  # uploaded_file | query_result | dashboard | scope
    source_id: int
    file_path: str = ""
    content: str = ""
    visibility: str = "shared_project"


class IndexReferenceRequest(BaseModel):
    """Index a reference-library document into the shared reference vector store.

    Not an :class:`AIBaseRequest`: industry-tier docs have no tenant/project, so
    those fields are optional and scope is carried by ``tier``.
    """
    tier: str
    tenant_id: int | None = None
    project_id: int | None = None
    user_id: int = 0
    document_id: int
    title: str = ""
    content: str = ""
    timestamp: float = 0.0
    signature: str = ""


class GenerateRelationshipsRequest(AIBaseRequest):
    pass


class SourceCatalogEntry(BaseModel):
    """A project source the AI may use, with its columns + description."""
    name: str
    columns: list[str] = Field(default_factory=list)
    description: str | None = None
    kind: str = "table"  # "table" (data source view) or "query" (saved query)


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


class SuggestDashboardRequest(AIBaseRequest):
    prompt: str = ""
    allowed_tables: list[str] = []
    knowledge_graph_context: dict[str, Any] = Field(default_factory=dict)


class SuggestDashboardsMultiRequest(AIBaseRequest):
    """Ask the planner for several distinct dashboard *plans* (lightweight).

    Unlike :class:`SuggestDashboardRequest` (which yields one fully-specced
    dashboard with executable SQL), this returns ``desired_count`` higher-level
    plans the user can pick from; the heavy validation/build happens on save via
    the existing generate-and-save-dashboard pipeline.
    """

    prompt: str = ""
    audience: str = ""
    desired_count: int = 3
    allowed_tables: list[str] = []
    kpis: list[str] = Field(default_factory=list)
    knowledge_graph_context: dict[str, Any] = Field(default_factory=dict)


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
    include_family: bool = True
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
    document_family: dict | None = None
    family_relationships: list[dict] = []
    family_members_suggested: list[dict] = []
    request_id: str = ""
    model_used: str = ""


class IntelligencePlanRequest(AIBaseRequest):
    """Ask the LLM to propose high-value diagnostic analyses for a project.

    The model acts as a senior analyst: given only the project's real schema
    and document summaries, it proposes the analyses a well-run company would
    run, writing the SQL in memory. No metric is hard-coded by the caller.
    """
    allowed_tables: list[str] = Field(default_factory=list)
    # Exact schema so the LLM never invents columns:
    # [{"table": <view>, "columns": [{"name": <col>, "type": <type>}]}]
    table_schema: list[dict] = Field(default_factory=list)
    documents: list[dict] = Field(default_factory=list)  # [{title, summary, tags}]
    # Evidence-backed join candidates the platform discovered from scope
    # metadata / matching keys. Each: {left_table, right_table, left_join_key,
    # right_join_key, relationship_type, join_confidence, confidence_reason,
    # row_multiplication_risk}. The planner may only propose multi-table
    # analyses that are supported by one of these hints.
    relationship_hints: list[dict] = Field(default_factory=list)
    reference_kpis: list[dict] = Field(default_factory=list)
    max_analyses: int = 6
    # 1 = executive/high-level (few, most leveraging) .. 5 = granular (many, detailed)
    granularity: int = 3
    project_context: dict = Field(default_factory=dict)
    # Compact Knowledge Graph digest from the platform (risks, gaps,
    # opportunities, warnings, recommended KPIs). Injected into the plan
    # prompt as HYPOTHESES the planner should validate/quantify/refute with
    # SQL — never asserted as findings without a query result behind them.
    knowledge_graph_context: dict = Field(default_factory=dict)


class PlannedAnalysis(BaseModel):
    id: str
    category: str = "trend"  # risk | trend | opportunity | relationship
    title: str = ""
    rationale: str = ""
    sql: str = ""
    chart_type: str = "bar"  # see _ALLOWED_PLAN_CHART_TYPES in routers/ai.py
    label_column: str = ""
    value_column: str = ""
    # Second metric used by dual_line/scatter/bubble/heatmap (color) and as the
    # target for gauge/bullet. Empty for single-metric charts.
    value_column_2: str = ""
    severity_hint: str = "watch"
    source_documents: list[str] = Field(default_factory=list)


class IntelligencePlanResponse(BaseModel):
    analyses: list[PlannedAnalysis] = Field(default_factory=list)
    request_id: str = ""
    model_used: str = ""


class IntelligenceFixSQLRequest(AIBaseRequest):
    """Repair a query that the Teiid engine rejected.

    Given the failing SQL, the engine's error message, and the exact schema,
    the model returns a corrected single-table query (or empty if unfixable).
    """
    sql: str = ""
    error: str = ""
    allowed_tables: list[str] = Field(default_factory=list)
    table_schema: list[dict] = Field(default_factory=list)


class IntelligenceFixSQLResponse(BaseModel):
    sql: str = ""
    request_id: str = ""
    model_used: str = ""


class ConversationTurnClassifyRequest(AIBaseRequest):
    """Classify a conversational-analytics follow-up turn.

    The platform sends the user's latest message plus the grounded state of the
    conversation (prior SQL, the executed result's real columns, the chart that
    is currently rendered). The model decides the intent and, for chart-only
    changes, emits a structured chart patch limited to the closed vocabulary the
    frontend renderer supports.
    """
    message: str = ""
    has_prior_result: bool = False
    prior_sql: str = ""
    result_columns: list[str] = Field(default_factory=list)
    numeric_columns: list[str] = Field(default_factory=list)
    categorical_columns: list[str] = Field(default_factory=list)
    row_count: int = 0
    current_chart: dict = Field(default_factory=dict)


class ConversationTurnClassifyResponse(BaseModel):
    intent: str = "new_analysis"
    chart: dict = Field(default_factory=dict)
    data_question: str | None = Field(
        default=None,
        description="The underlying data question, with chart/presentation wording removed and ambiguous phrasing clarified. Null for chart_change and explain.",
    )
    confidence: float = 0.0
    reason: str = ""
    request_id: str = ""
    model_used: str = ""


class InterpretAnalysisInput(BaseModel):
    id: str
    category: str = "trend"
    title: str = ""
    rationale: str = ""
    chart_type: str = "bar"
    columns: list[str] = Field(default_factory=list)
    rows: list[dict] = Field(default_factory=list)  # small sample of result rows
    row_count: int = 0
    document_context: str = ""  # for document-driven analyses


class IntelligenceInterpretRequest(AIBaseRequest):
    """Turn executed query results (or document context) into business prose."""
    analyses: list[InterpretAnalysisInput] = Field(default_factory=list)
    project_context: dict = Field(default_factory=dict)


class InterpretedInsight(BaseModel):
    id: str
    title: str = ""
    summary: str = ""
    severity: str = "info"  # critical | urgent | watch | opportunity | info
    callout_type: str = ""  # risk | opportunity | info | ""
    callout_text: str = ""
    recommendation: str = ""


class IntelligenceInterpretResponse(BaseModel):
    insights: list[InterpretedInsight] = Field(default_factory=list)
    request_id: str = ""
    model_used: str = ""


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


class ProjectInsightRequest(AIBaseRequest):
    """Generate a project-scoped executive insight report for ONE project.

    The platform supplies the selected project's authorized context (metadata,
    tables, documents, saved queries, dashboards, KPIs, Knowledge Graph). The
    model reasons over ONLY this project's context — grounded in the Project
    Insight Best Practices — and returns the structured Project Insight
    contract. It must not summarize the tenant or other projects.
    """
    project: dict = Field(default_factory=dict)  # {id, name, status}
    tables: list[dict] = Field(default_factory=list)
    documents: list[dict] = Field(default_factory=list)
    queries: list[dict] = Field(default_factory=list)
    dashboards: list[dict] = Field(default_factory=list)
    kpis: list[str] = Field(default_factory=list)
    knowledge_graph_context: dict = Field(default_factory=dict)
    recent_activity: dict = Field(default_factory=dict)
    project_context: dict = Field(default_factory=dict)


class ProjectInsightExecutiveSummary(BaseModel):
    summary: str = ""
    critical: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    opportunities: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class ProjectInsightResponse(BaseModel):
    executiveSummary: ProjectInsightExecutiveSummary = Field(
        default_factory=ProjectInsightExecutiveSummary
    )
    questionsToAsk: list[dict] = Field(default_factory=list)
    trendDetection: list[dict] = Field(default_factory=list)
    recommendedDashboards: list[dict] = Field(default_factory=list)
    recommendedQueries: list[dict] = Field(default_factory=list)
    recommendedKpis: list[dict] = Field(default_factory=list)
    insightValidationWorkflow: list[dict] = Field(default_factory=list)
    request_id: str = ""
    model_used: str = ""


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


class WidgetValidationExpectations(BaseModel):
    """What a widget's executed result must satisfy to be saved (judge stage)."""
    minimum_rows: int = 1
    required_columns: list[str] = Field(default_factory=list)
    non_null_columns: list[str] = Field(default_factory=list)
    chart_requires_multiple_rows: bool = False
    empty_result_action: str = "drop_widget"


class WidgetReferenceLine(BaseModel):
    label: str = ""
    value: float | None = None
    source_document: str = ""


class DashboardWidgetSuggestion(BaseModel):
    # Insight-first chart catalog: kpi/kpi_grid | bar | horizontal_bar |
    # stacked_bar | grouped_bar | line | area | dual_line | pie | donut |
    # table | pivot_table | heatmap | scatter | bubble | treemap | waterfall |
    # funnel | gauge | bullet | radar | sparkline_table | narrative_insight
    type: str
    title: str
    subtitle: str = ""
    business_question: str = ""
    sql: str = ""
    chart_subtype: str = ""
    x_column: str | None = ""
    y_column: str | None = ""
    label_column: str | None = ""
    value_column: str | None = ""
    value_column_2: str | None = ""
    series_column: str | None = ""
    target_column: str | None = ""
    aggregation: str | None = ""
    reference_lines: list[WidgetReferenceLine] = Field(default_factory=list)
    drilldown_fields: list[str] = Field(default_factory=list)
    validation_expectations: WidgetValidationExpectations = Field(
        default_factory=WidgetValidationExpectations
    )
    priority_score: int = 0
    confidence_score: float = 0.0
    # Optional layout hints from the planner.
    gridX: int | None = None
    gridY: int | None = None
    gridW: int | None = None
    gridH: int | None = None


class DashboardSuggestion(BaseModel):
    title: str
    description: str = ""
    business_domain: str = ""
    intended_audience: str = ""
    executive_summary: str = ""
    widgets: list[DashboardWidgetSuggestion]


class SuggestDashboardResponse(BaseModel):
    suggestions: list[DashboardSuggestion]
    request_id: str
    model_used: str


class DashboardPlanWidget(BaseModel):
    """A widget outline within a dashboard plan, including renderable SQL.

    ``sql`` is grounded in the project's real tables so the platform can execute
    it and return real preview data for the Generate-tab dashboard previews.
    ``narrative_insight`` / risk / gap widgets carry an empty ``sql``.
    """

    title: str = ""
    chart_type: str = ""
    business_question: str = ""
    sql: str = ""
    label_column: str = ""
    value_column: str = ""


class DashboardPlanSuggestion(BaseModel):
    """A high-level dashboard plan the user can preview and choose to save."""

    title: str
    description: str = ""
    business_purpose: str = ""
    audience: str = ""
    widgets: list[DashboardPlanWidget] = Field(default_factory=list)
    kpis: list[str] = Field(default_factory=list)
    data_sources: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    quality_score: int = 0


class SuggestDashboardsMultiResponse(BaseModel):
    suggestions: list[DashboardPlanSuggestion]
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
