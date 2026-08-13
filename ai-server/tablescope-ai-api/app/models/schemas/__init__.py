"""Pydantic schemas for the AI API, split by feature.

Every public schema is re-exported here so ``from app.models.schemas import X``
keeps working for callers regardless of which module defines it.
"""

from .actions import (
    DraftActionRequest,
    DraftActionResponse,
    DraftActionSubtask,
    DraftActionSuccessCriterion,
)
from .analysis import (
    FirstPassResult,
    IntelligenceFixSQLRequest,
    IntelligenceFixSQLResponse,
    IntelligenceInterpretRequest,
    IntelligenceInterpretResponse,
    IntelligencePlanRequest,
    IntelligencePlanResponse,
    InterpretAnalysisInput,
    InterpretedInsight,
    PlannedAnalysis,
)
from .ask import (
    AskRequest,
    AskResponse,
)
from .common import (
    AIBaseRequest,
    HealthResponse,
    QueryInfo,
)
from .context import (
    ContextPackage,
    VectorPayload,
)
from .conversation import (
    ConversationTurnClassifyRequest,
    ConversationTurnClassifyResponse,
)
from .dashboard import (
    DashboardPlanSuggestion,
    DashboardPlanWidget,
    DashboardSuggestion,
    DashboardWidgetSuggestion,
    SuggestDashboardRequest,
    SuggestDashboardResponse,
    SuggestDashboardsMultiRequest,
    SuggestDashboardsMultiResponse,
    WidgetReferenceLine,
    WidgetValidationExpectations,
)
from .documents import (
    DocumentProfileRequest,
    DocumentProfileResponse,
)
from .family import (
    FamilySummarizeRequest,
    FamilySummarizeResponse,
)
from .grounding import (
    GroundingEvidence,
    GroundingKGNode,
    GroundingKPI,
    GroundingPassage,
    GroundingSearchRequest,
    GroundingSearchResponse,
)
from .file_analysis import (
    AnalyzeFileRequest,
    AnalyzeFileResponse,
)
from .indexing import (
    IndexDocumentRequest,
    IndexReferenceRequest,
)
from .insight_card_match import (
    InsightCardCandidate,
    SelectInsightCardRequest,
    SelectInsightCardResponse,
)
from .kg import (
    KnowledgeGraphCard,
    KnowledgeGraphInsightRequest,
    KnowledgeGraphInsightResponse,
)
from .project_insight import (
    ProjectInsightExecutiveSummary,
    ProjectInsightRequest,
    ProjectInsightResponse,
)
from .query import (
    GenerateSQLRequest,
    GenerateSQLResponse,
    MatchQueryRequest,
    MatchQueryResponse,
    SelectedField,
    SelectedSource,
    SourceCatalogEntry,
)
from .reference import (
    ReferenceSuggestRequest,
    ReferenceSuggestResponse,
    ReferenceSummarizeRequest,
    ReferenceSummarizeResponse,
)
from .relationships import (
    GenerateRelationshipsRequest,
    GenerateRelationshipsResponse,
    RelationshipSuggestion,
)
from .scopes import (
    AnalyzeScopesRequest,
    AnalyzeScopesResponse,
    ScopeSuggestion,
)

__all__ = [
    "AIBaseRequest",
    "AnalyzeFileRequest",
    "AnalyzeFileResponse",
    "AnalyzeScopesRequest",
    "AnalyzeScopesResponse",
    "AskRequest",
    "AskResponse",
    "ContextPackage",
    "ConversationTurnClassifyRequest",
    "ConversationTurnClassifyResponse",
    "DashboardPlanSuggestion",
    "DashboardPlanWidget",
    "DashboardSuggestion",
    "DashboardWidgetSuggestion",
    "DocumentProfileRequest",
    "DocumentProfileResponse",
    "DraftActionRequest",
    "DraftActionResponse",
    "DraftActionSubtask",
    "DraftActionSuccessCriterion",
    "FamilySummarizeRequest",
    "FamilySummarizeResponse",
    "GroundingEvidence",
    "GroundingKGNode",
    "GroundingKPI",
    "GroundingPassage",
    "GroundingSearchRequest",
    "GroundingSearchResponse",
    "GenerateRelationshipsRequest",
    "GenerateRelationshipsResponse",
    "GenerateSQLRequest",
    "GenerateSQLResponse",
    "HealthResponse",
    "IndexDocumentRequest",
    "IndexReferenceRequest",
    "IntelligenceFixSQLRequest",
    "IntelligenceFixSQLResponse",
    "IntelligenceInterpretRequest",
    "IntelligenceInterpretResponse",
    "IntelligencePlanRequest",
    "IntelligencePlanResponse",
    "FirstPassResult",
    "InsightCardCandidate",
    "InterpretAnalysisInput",
    "InterpretedInsight",
    "KnowledgeGraphCard",
    "KnowledgeGraphInsightRequest",
    "KnowledgeGraphInsightResponse",
    "MatchQueryRequest",
    "MatchQueryResponse",
    "PlannedAnalysis",
    "ProjectInsightExecutiveSummary",
    "ProjectInsightRequest",
    "ProjectInsightResponse",
    "QueryInfo",
    "ReferenceSuggestRequest",
    "ReferenceSuggestResponse",
    "ReferenceSummarizeRequest",
    "ReferenceSummarizeResponse",
    "RelationshipSuggestion",
    "ScopeSuggestion",
    "SelectInsightCardRequest",
    "SelectInsightCardResponse",
    "SelectedField",
    "SelectedSource",
    "SourceCatalogEntry",
    "SuggestDashboardRequest",
    "SuggestDashboardResponse",
    "SuggestDashboardsMultiRequest",
    "SuggestDashboardsMultiResponse",
    "VectorPayload",
    "WidgetReferenceLine",
    "WidgetValidationExpectations",
]
