"""Base request envelope and small shared value objects."""

from pydantic import BaseModel


class AIBaseRequest(BaseModel):
    """Base request — every AI call requires tenant/user/project context."""
    tenant_id: int
    user_id: int
    project_id: int
    signature: str = ""
    timestamp: float = 0.0
    # Optional model override and routing capability supplied by the platform
    # LLM Framework. When omitted, the AI server falls back to static config.
    model: str | None = None
    capability: str | None = None


class QueryInfo(BaseModel):
    """Minimal query info for scope analysis."""
    id: int
    name: str
    sql: str


class HealthResponse(BaseModel):
    status: str
    ollama: str
    qdrant: str
    gpu: str
