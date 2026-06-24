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
from app.models.ai_project_graph import AIProjectGraphEdge, AIProjectGraphNode
from app.models.ai_reference_catalog import (
    AIReferenceCatalog,
    AIReferenceKPI,
    AIReferenceTag,
    TenantCustomKPI,
    TenantCustomTag,
    TenantReferenceCatalog,
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
from app.models.file_source_meta import FileSourceMeta
from app.models.grid_preference import GridPreference
from app.models.intelligence_snapshot import IntelligenceSnapshot
from app.models.knowledge_graph_snapshot import AIProjectGraphSnapshot
from app.models.organization_vdb import OrganizationVDB
from app.models.project import Project, ProjectMember
from app.models.project_asset import ProjectAsset
from app.models.query_scope import QueryScope
from app.models.reference_library import (
    ReferenceAdditionRequest,
    ReferenceDocument,
    ReferenceDocumentAssignment,
    ReferenceLibraryImportBatch,
    ReferenceLibraryImportRow,
)
from app.models.report import Report
from app.models.saas_object_data_source import SaasObjectDataSource
from app.models.saved_query import SavedQuery
from app.models.scope_canvas_layout import ScopeCanvasLayout
from app.models.scope_set import ScopeSet
from app.models.shared_vdb import SharedVDB
from app.models.tenant import Tenant
from app.models.tenant_data_plane import TenantDataPlane, TenantSecretRef
from app.models.tenant_membership import TenantAuthBinding, TenantMembership
from app.models.user import User
from app.models.user_vdb import UserVDB

__all__ = [
    "AIProjectGraphEdge",
    "AIProjectGraphNode",
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
    "FileSourceMeta",
    "GridPreference",
    "IntelligenceSnapshot",
    "AIProjectGraphSnapshot",
    "OrganizationVDB",
    "Project",
    "ProjectAsset",
    "ProjectMember",
    "QueryScope",
    "ReferenceAdditionRequest",
    "ReferenceDocument",
    "ReferenceDocumentAssignment",
    "ReferenceLibraryImportBatch",
    "ReferenceLibraryImportRow",
    "SaasObjectDataSource",
    "SavedQuery",
    "SharedVDB",
    "Tenant",
    "TenantDataPlane",
    "TenantSecretRef",
    "TenantAuthBinding",
    "TenantMembership",
    "User",
    "UserVDB",
]
