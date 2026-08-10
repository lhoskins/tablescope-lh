"""Schemas for selecting a precomputed Insight Card to answer a question."""

from pydantic import BaseModel, Field

from .common import AIBaseRequest


class InsightCardCandidate(BaseModel):
    """One already-computed card the platform is offering as a candidate.

    The model judges relevance from the chart's data shape (series labels,
    axes, trend) and summary, never from the title alone and never from SQL.
    It never proposes new analysis of its own.
    """
    insight_id: str
    title: str = ""
    summary: str = ""
    chart_signature: str = ""
    series: str = ""
    trend: str = ""


class SelectInsightCardRequest(AIBaseRequest):
    """Ask the model to pick the one candidate card (if any) that directly
    answers ``question``, when a fresh query could not be generated/executed
    for it. The platform has already narrowed ``candidates`` to cards the
    caller is authorized to see; the model's only job is relevance judgment.
    """
    question: str = ""
    candidates: list[InsightCardCandidate] = Field(default_factory=list)


class SelectInsightCardResponse(BaseModel):
    insight_id: str | None = None
    confidence: float = 0.0
    reason: str = ""
    request_id: str = ""
    model_used: str = ""
