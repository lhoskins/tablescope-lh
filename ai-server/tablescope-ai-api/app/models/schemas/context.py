"""Vector payload and the controlled context package sent to the LLM."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .grounding import GroundingEvidence


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


class VectorAccessClaims(BaseModel):
    """Platform-minted authorization facts for one vector retrieval.

    The signed permission callback returns these claims only after checking
    current project ownership or active membership. Every identifier is bound
    back to the signed request envelope before Qdrant is queried.
    """

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    tenant_id: int
    project_id: int
    principal_user_id: int
    project_access: Literal["owner", "active_member"]
    project_visibility: Literal["shared", "private"]
    can_read_shared_documents: bool = True
    private_document_owner_user_id: int

    @model_validator(mode="after")
    def private_owner_must_be_principal(self) -> "VectorAccessClaims":
        if self.private_document_owner_user_id != self.principal_user_id:
            raise ValueError("private document owner must match the authorized principal")
        return self


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
    grounding_evidence: GroundingEvidence | None = None
