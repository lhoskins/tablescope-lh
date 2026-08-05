"""Vector payload and the controlled context package sent to the LLM."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


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
