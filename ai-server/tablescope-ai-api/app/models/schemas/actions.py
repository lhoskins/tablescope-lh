"""Schemas for AI-drafted project actions."""

from typing import Any

from pydantic import BaseModel, Field

from .common import AIBaseRequest


class DraftActionSubtask(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: str = ""
    is_required: bool = True
    status: str = "not_started"


class DraftActionSuccessCriterion(BaseModel):
    name: str = Field(..., min_length=1, max_length=500)
    description: str = ""
    target_value: str | float | int | None = None
    directionality: str = "increase"
    cadence: str = "monthly"
    unit: str = ""
    format: str = ""


class DraftActionRequest(AIBaseRequest):
    insight_type: str
    title: str
    summary: str
    recommended_action: str = ""
    severity: str = "info"
    sources: dict[str, Any] = Field(default_factory=dict)
    supporting_sources: list[str] = Field(default_factory=list)
    explanation: dict[str, Any] | None = None


class DraftActionResponse(BaseModel):
    title: str = ""
    description: str = ""
    subtasks: list[DraftActionSubtask] = Field(default_factory=list)
    success_criteria: list[DraftActionSuccessCriterion] = Field(default_factory=list)
    model_used: str = ""
    request_id: str = ""
