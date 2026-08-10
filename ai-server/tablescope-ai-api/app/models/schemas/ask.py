"""Schemas for the ``/ai/ask`` endpoint."""

from typing import Any

from pydantic import BaseModel, Field

from .common import AIBaseRequest
from .grounding import GroundingEvidence


class AskRequest(AIBaseRequest):
    question: str
    scope: str = "project"  # project | personal | shared_project
    include_query_history: bool = True
    include_dashboard_context: bool = True
    # Prior turns of the same conversation (oldest→newest), each
    # {"role": "user"|"assistant", "content": "..."}. Lets the model resolve
    # follow-up references ("explain more", "the second option").
    history: list[dict[str, Any]] = Field(default_factory=list)
    # Compact, AI-safe Knowledge Graph summary; grounds prose answers in the
    # same measured risks/gaps/KPIs used by dashboard and query generation.
    knowledge_graph_context: dict[str, Any] = Field(default_factory=dict)
    # Proactive hybrid retrieval evidence (document passages, KG nodes, KPIs).
    grounding_evidence: GroundingEvidence | None = None
    # Optional live query result the platform-api already executed. When
    # present, the LLM synthesizes the final answer from this data rather than
    # generating a new query.
    data_result: dict[str, Any] | None = None
    # Optional precomputed insight card(s) the question matched. When present,
    # the LLM answers from the grounded card analysis instead of inventing one.
    matched_insights: list[dict[str, Any]] | None = None


class AskResponse(BaseModel):
    answer: str
    model_used: str
    request_id: str
    context_summary: dict[str, Any] = Field(default_factory=dict)
    audit_id: int | None = None
    # Manifest of evidence used to ground the answer (when provided).
    grounding_manifest: dict[str, Any] | None = None
