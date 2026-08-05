"""Schemas for document and reference-library vector indexing."""

from pydantic import BaseModel

from .common import AIBaseRequest


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
