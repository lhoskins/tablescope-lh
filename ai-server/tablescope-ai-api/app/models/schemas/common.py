"""Base request envelope and small shared value objects."""

from pydantic import BaseModel


class AIBaseRequest(BaseModel):
    """Base request — every AI call requires tenant/user/project context."""
    tenant_id: int
    user_id: int
    project_id: int
    signature: str = ""
    timestamp: float = 0.0
    # The platform-api conversation/turn this call was made for, when the
    # caller is a conversational-analytics turn. Optional and log-only --
    # threaded through so a log line can be traced back to the exact turn
    # instead of guessed from timestamp proximity across every tenant's
    # concurrent requests.
    conversation_id: int | None = None
    turn_id: int | None = None
    # Optional model override and routing capability supplied by the platform
    # LLM Framework. When omitted, the AI server falls back to static config.
    # Despite the name history, this carries whichever backend is actively
    # routed for the capability -- Ollama or vLLM alike (see llm_client.py's
    # module docstring).
    model: str | None = None
    llm_target_url: str | None = None
    routing_version: int | None = None
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
