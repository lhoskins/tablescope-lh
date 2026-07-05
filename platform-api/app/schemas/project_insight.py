"""Project Insight schemas — the project-scoped executive insight report.

Distinct from Business Insight (tenant-wide). Recommended dashboards, queries,
and KPIs are AI suggestions and do not need to already exist. The Insight
Validation Workflow supports Reviewed / Acknowledged only (no Approve/Reject).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ProjectInsightProject(BaseModel):
    id: int
    name: str
    status: str = "Active"


class ExecutiveSummary(BaseModel):
    summary: str = ""
    critical: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    opportunities: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class WhatChangedSinceLastVisit(BaseModel):
    newFilesAdded: int = 0
    changedDataSources: int = 0
    newRisksIdentified: int = 0
    newQueries: int = 0
    newDashboards: int = 0
    updatedKnowledgeGraph: int = 0
    changeLogLink: str = ""


class ProjectInsightResponse(BaseModel):
    project: ProjectInsightProject
    generatedAt: str = ""
    lastUpdatedAt: str = ""
    executiveSummary: ExecutiveSummary = Field(default_factory=ExecutiveSummary)
    questionsToAsk: list[dict[str, Any]] = Field(default_factory=list)
    trendDetection: list[dict[str, Any]] = Field(default_factory=list)
    recommendedDashboards: list[dict[str, Any]] = Field(default_factory=list)
    recommendedQueries: list[dict[str, Any]] = Field(default_factory=list)
    recommendedKpis: list[dict[str, Any]] = Field(default_factory=list)
    # Business Insight-style cards, grouped and severity-normalized. Deterministic
    # (grounded in the project's real data), so present even when aiAvailable=False.
    risks: list[dict[str, Any]] = Field(default_factory=list)
    trends: list[dict[str, Any]] = Field(default_factory=list)
    opportunities: list[dict[str, Any]] = Field(default_factory=list)
    whatChangedSinceLastVisit: WhatChangedSinceLastVisit = Field(
        default_factory=WhatChangedSinceLastVisit
    )
    insightValidationWorkflow: list[dict[str, Any]] = Field(default_factory=list)
    # True when the AI server produced the report; False when it degraded to an
    # empty structure (AI unavailable) so the UI can show a helpful state.
    aiAvailable: bool = True


class AcknowledgeInsightRequest(BaseModel):
    note: str | None = None
    # Snapshot of the insight at review time (so the Reviewed list survives
    # report regeneration). All optional; unknown fields ignored.
    title: str | None = None
    summary: str | None = None
    category: str | None = None
    severity: str | None = None


class AcknowledgeInsightResponse(BaseModel):
    insightId: str
    status: str = "reviewed"
    acknowledgedByUserId: int | None = None
    acknowledgedByName: str = ""
    acknowledgedAt: datetime | None = None


class ReviewedInsight(BaseModel):
    insightId: str
    title: str = ""
    summary: str = ""
    category: str = ""
    severity: str = ""
    note: str | None = None
    reviewedByUserId: int | None = None
    reviewedByName: str = ""
    reviewedAt: datetime | None = None


class ReviewedInsightsResponse(BaseModel):
    items: list[ReviewedInsight] = Field(default_factory=list)


class ReopenInsightResponse(BaseModel):
    insightId: str
    status: str = "reopened"
