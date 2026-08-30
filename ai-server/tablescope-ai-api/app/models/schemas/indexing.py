"""Schemas for document and reference-library vector indexing."""

from typing import Literal

from pydantic import BaseModel, model_validator

from .common import AIBaseRequest


class IndexDocumentRequest(AIBaseRequest):
    document_id: int
    source_type: str  # uploaded_file | query_result | dashboard | scope
    source_id: int
    file_path: str = ""
    content: str = ""
    visibility: Literal["shared_project", "private"] = "shared_project"


class IndexReferenceRequest(BaseModel):
    """Index a reference-library document into the shared reference vector store.

    Not an :class:`AIBaseRequest`: industry-tier docs have no tenant/project, so
    those fields are optional and scope is carried by ``tier``.
    """
    tier: Literal["industry", "company", "project"]
    tenant_id: int | None = None
    project_id: int | None = None
    user_id: int = 0
    document_id: int
    title: str = ""
    content: str = ""
    timestamp: float = 0.0
    signature: str = ""

    @model_validator(mode="after")
    def require_tier_identifiers(self) -> "IndexReferenceRequest":
        if self.tier == "company" and self.tenant_id is None:
            raise ValueError("company reference vectors require tenant_id")
        if self.tier == "project" and (self.tenant_id is None or self.project_id is None):
            raise ValueError("project reference vectors require tenant_id and project_id")
        return self
