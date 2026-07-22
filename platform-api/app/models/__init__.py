"""SQLAlchemy ORM models for the platform API."""

from app.models.ai_asset_metadata import (
    AIAssetKPI,
    AIAssetKPISuggestion,
    AIAssetTag,
    AIAssetTagSuggestion,
)
from app.models.ai_conversation import (
    AiConversation,
    AiConversationMessage,
)
from app.models.ai_governance_audit import AIGovernanceAuditEvent
from app.models.ai_project_graph import AIProjectGraphEdge, AIProjectGraphNode
from app.models.ai_reference_catalog import (
    AIReferenceCatalog,
    AIReferenceKPI,
    AIReferenceTag,
    TenantCustomKPI,
    TenantCustomTag,
    TenantReferenceCatalog,
)
from app.models.analytical_method_catalog import (
    AnalyticalMethod,
    AnalyticalSharedPolicy,
    MethodCatalog,
    MethodCatalogAuditLog,
    MethodCatalogVersion,
    MethodSelectionMatrix,
)
from app.models.analytics_conversation import (
    AnalyticsConversation,
    AnalyticsConversationTurn,
)
from app.models.audit_event import AuditEvent
from app.models.base import Base
from app.models.billing import (
    BillingCustomer,
    BillingEvent,
    BillingSubscription,
    SubscriptionTierCatalog,
    TenantProvisioningRequest,
)
from app.models.business_insight_result import BusinessInsightResult
from app.models.connector_credential import ConnectorCredential
from app.models.dashboard import Dashboard
from app.models.data_source_ai_profile import (
    DataSourceAIProfile,
    DataSourceAIRecommendation,
    DataSourceFieldProfile,
    DataSourceTag,
)
from app.models.database_connection import DatabaseConnection
from app.models.database_data_source import DatabaseDataSource, DataSourceColumn
from app.models.database_data_source_assignment import (
    DatabaseDataSourceAssignment,
)
from app.models.file_source_meta import FileSourceMeta
from app.models.grid_preference import GridPreference
from app.models.home_pin import HomePin
from app.models.insight_feedback import InsightFeedback, InsightFeedbackReviewEvent
from app.models.intelligence_snapshot import IntelligenceSnapshot
from app.models.knowledge_graph_lifecycle import (
    KnowledgeGraph,
    KnowledgeGraphBuild,
    KnowledgeGraphHealthCheck,
    KnowledgeGraphVersion,
)
from app.models.knowledge_graph_snapshot import AIProjectGraphSnapshot
from app.models.mfa_phone_factor import MfaPhoneFactor
from app.models.mfa_sms_event import MfaSmsEvent
from app.models.organization_vdb import OrganizationVDB
from app.models.project import Project, ProjectMember
from app.models.project_asset import ProjectAsset
from app.models.project_context import (
    ProjectBusinessContext,
    ProjectContextAuditEvent,
    ProjectGoal,
    ProjectGoalMetricLink,
    ProjectGoalRiskLink,
    ProjectMetric,
    ProjectMetricTarget,
    ProjectRisk,
    ProjectRiskMetricLink,
)
from app.models.project_insight_acknowledgement import (
    ProjectInsightAcknowledgement,
)
from app.models.project_intelligence_snapshot import (
    ProjectIntelligenceSnapshot,
)
from app.models.query_scope import QueryScope
from app.models.reference_library import (
    ReferenceAdditionRequest,
    ReferenceDocument,
    ReferenceDocumentAssignment,
    ReferenceLibraryImportBatch,
    ReferenceLibraryImportRow,
)
from app.models.report import Report
from app.models.repository import (
    RepositoryConnection,
    RepositoryItem,
    RepositoryProfile,
    RepositoryScan,
)
from app.models.saas_object_data_source import SaasObjectDataSource
from app.models.saved_query import SavedQuery
from app.models.scope_canvas_layout import ScopeCanvasLayout
from app.models.scope_set import ScopeSet
from app.models.shared_vdb import SharedVDB
from app.models.tenant import Tenant, TenantAllowedDomain
from app.models.tenant_ai_governance import (
    TenantAIGovernancePolicy,
    TenantAIMethodPolicy,
)
from app.models.tenant_data_plane import TenantDataPlane, TenantSecretRef
from app.models.tenant_membership import TenantAuthBinding, TenantMembership
from app.models.user import User
from app.models.user_vdb import UserVDB

__all__ = [
    "AIProjectGraphEdge",
    "AIProjectGraphNode",
    "AIGovernanceAuditEvent",
    "AnalyticsConversation",
    "AnalyticsConversationTurn",
    "AiConversation",
    "AiConversationMessage",
    "AuditEvent",
    "Report",
    "ScopeCanvasLayout",
    "ScopeSet",
    "AIAssetKPI",
    "AIAssetKPISuggestion",
    "AIAssetTag",
    "AIAssetTagSuggestion",
    "AIReferenceCatalog",
    "AIReferenceKPI",
    "AIReferenceTag",
    "TenantCustomKPI",
    "TenantCustomTag",
    "TenantReferenceCatalog",
    "AnalyticalMethod",
    "AnalyticalSharedPolicy",
    "MethodCatalog",
    "MethodCatalogAuditLog",
    "MethodCatalogVersion",
    "MethodSelectionMatrix",
    "Base",
    "BillingCustomer",
    "BillingEvent",
    "BillingSubscription",
    "SubscriptionTierCatalog",
    "TenantProvisioningRequest",
    "ConnectorCredential",
    "Dashboard",
    "DataSourceAIProfile",
    "DataSourceAIRecommendation",
    "DataSourceFieldProfile",
    "DataSourceTag",
    "DatabaseConnection",
    "DataSourceColumn",
    "DatabaseDataSource",
    "DatabaseDataSourceAssignment",
    "BusinessInsightResult",
    "FileSourceMeta",
    "GridPreference",
    "HomePin",
    "InsightFeedback",
    "InsightFeedbackReviewEvent",
    "IntelligenceSnapshot",
    "KnowledgeGraph",
    "KnowledgeGraphBuild",
    "KnowledgeGraphHealthCheck",
    "KnowledgeGraphVersion",
    "AIProjectGraphSnapshot",
    "MfaPhoneFactor",
    "MfaSmsEvent",
    "OrganizationVDB",
    "Project",
    "ProjectAsset",
    "ProjectBusinessContext",
    "ProjectContextAuditEvent",
    "ProjectGoal",
    "ProjectGoalMetricLink",
    "ProjectGoalRiskLink",
    "ProjectInsightAcknowledgement",
    "ProjectIntelligenceSnapshot",
    "ProjectMember",
    "ProjectMetric",
    "ProjectMetricTarget",
    "ProjectRisk",
    "ProjectRiskMetricLink",
    "QueryScope",
    "ReferenceAdditionRequest",
    "ReferenceDocument",
    "ReferenceDocumentAssignment",
    "ReferenceLibraryImportBatch",
    "ReferenceLibraryImportRow",
    "RepositoryConnection",
    "RepositoryItem",
    "RepositoryProfile",
    "RepositoryScan",
    "SaasObjectDataSource",
    "SavedQuery",
    "SharedVDB",
    "Tenant",
    "TenantAllowedDomain",
    "TenantAIGovernancePolicy",
    "TenantAIMethodPolicy",
    "TenantDataPlane",
    "TenantSecretRef",
    "TenantAuthBinding",
    "TenantMembership",
    "User",
    "UserVDB",
]
