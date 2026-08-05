"""Schemas for the project-scoped executive insight report."""

from pydantic import BaseModel, Field

from .common import AIBaseRequest


class ProjectInsightRequest(AIBaseRequest):
    """Generate a project-scoped executive insight report for ONE project.

    The platform supplies the selected project's authorized context (metadata,
    tables, documents, saved queries, dashboards, KPIs, Knowledge Graph). The
    model reasons over ONLY this project's context — grounded in the Project
    Insight Best Practices — and returns the structured Project Insight
    contract. It must not summarize the tenant or other projects.
    """
    project: dict = Field(default_factory=dict)  # {id, name, status}
    tables: list[dict] = Field(default_factory=list)
    documents: list[dict] = Field(default_factory=list)
    queries: list[dict] = Field(default_factory=list)
    dashboards: list[dict] = Field(default_factory=list)
    kpis: list[str] = Field(default_factory=list)
    knowledge_graph_context: dict = Field(default_factory=dict)
    recent_activity: dict = Field(default_factory=dict)
    project_context: dict = Field(default_factory=dict)


class ProjectInsightExecutiveSummary(BaseModel):
    summary: str = ""
    critical: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    opportunities: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class ProjectInsightResponse(BaseModel):
    executiveSummary: ProjectInsightExecutiveSummary = Field(
        default_factory=ProjectInsightExecutiveSummary
    )
    questionsToAsk: list[dict] = Field(default_factory=list)
    trendDetection: list[dict] = Field(default_factory=list)
    recommendedDashboards: list[dict] = Field(default_factory=list)
    recommendedQueries: list[dict] = Field(default_factory=list)
    recommendedKpis: list[dict] = Field(default_factory=list)
    insightValidationWorkflow: list[dict] = Field(default_factory=list)
    request_id: str = ""
    model_used: str = ""
