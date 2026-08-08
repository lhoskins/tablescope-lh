"""Schemas for conversational-analytics turn classification."""

from pydantic import BaseModel, Field

from .common import AIBaseRequest


class ConversationTurnClassifyRequest(AIBaseRequest):
    """Classify a conversational-analytics follow-up turn.

    The platform sends the user's latest message plus the grounded state of the
    conversation (prior SQL, the executed result's real columns, the chart that
    is currently rendered). The model decides the intent and, for chart-only
    changes, emits a structured chart patch limited to the closed vocabulary the
    frontend renderer supports.
    """
    message: str = ""
    has_prior_result: bool = False
    prior_sql: str = ""
    result_columns: list[str] = Field(default_factory=list)
    numeric_columns: list[str] = Field(default_factory=list)
    categorical_columns: list[str] = Field(default_factory=list)
    row_count: int = 0
    current_chart: dict = Field(default_factory=dict)


class ConversationTurnClassifyResponse(BaseModel):
    intent: str = "new_analysis"
    chart: dict = Field(default_factory=dict)
    data_question: str | None = Field(
        default=None,
        description="The underlying data question, with chart/presentation wording removed and ambiguous phrasing clarified. Null for chart_change and explain.",
    )
    confidence: float = 0.0
    reason: str = ""
    request_id: str = ""
    model_used: str = ""
