"""Schemas for document profiling."""

from pydantic import BaseModel


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
    # Document families are project-scoped. Tenant-wide libraries (company /
    # industry reference docs) request profiling with this disabled so the
    # family-classification step never runs for them.
    include_family: bool = True
    signature: str = ""
    timestamp: float = 0.0
    # Optional routing overrides from the LLM Framework.
    model: str | None = None
    ollama_url: str | None = None
    routing_version: int | None = None


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
