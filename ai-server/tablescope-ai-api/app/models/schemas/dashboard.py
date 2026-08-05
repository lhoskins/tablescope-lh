"""Schemas for dashboard suggestion (single spec and multi-plan)."""

from typing import Any

from pydantic import BaseModel, Field

from .common import AIBaseRequest


class SuggestDashboardRequest(AIBaseRequest):
    prompt: str = ""
    allowed_tables: list[str] = []
    knowledge_graph_context: dict[str, Any] = Field(default_factory=dict)


class SuggestDashboardsMultiRequest(AIBaseRequest):
    """Ask the planner for several distinct dashboard *plans* (lightweight).

    Unlike :class:`SuggestDashboardRequest` (which yields one fully-specced
    dashboard with executable SQL), this returns ``desired_count`` higher-level
    plans the user can pick from; the heavy validation/build happens on save via
    the existing generate-and-save-dashboard pipeline.
    """

    prompt: str = ""
    audience: str = ""
    desired_count: int = 3
    allowed_tables: list[str] = []
    kpis: list[str] = Field(default_factory=list)
    knowledge_graph_context: dict[str, Any] = Field(default_factory=dict)


class WidgetValidationExpectations(BaseModel):
    """What a widget's executed result must satisfy to be saved (judge stage)."""
    minimum_rows: int = 1
    required_columns: list[str] = Field(default_factory=list)
    non_null_columns: list[str] = Field(default_factory=list)
    chart_requires_multiple_rows: bool = False
    empty_result_action: str = "drop_widget"


class WidgetReferenceLine(BaseModel):
    label: str = ""
    value: float | None = None
    source_document: str = ""


class DashboardWidgetSuggestion(BaseModel):
    # Insight-first chart catalog: kpi/kpi_grid | bar | horizontal_bar |
    # stacked_bar | grouped_bar | line | area | dual_line | pie | donut |
    # table | pivot_table | heatmap | scatter | bubble | treemap | waterfall |
    # funnel | gauge | bullet | radar | sparkline_table | narrative_insight
    type: str
    title: str
    subtitle: str = ""
    business_question: str = ""
    sql: str = ""
    chart_subtype: str = ""
    x_column: str | None = ""
    y_column: str | None = ""
    label_column: str | None = ""
    value_column: str | None = ""
    value_column_2: str | None = ""
    series_column: str | None = ""
    target_column: str | None = ""
    aggregation: str | None = ""
    reference_lines: list[WidgetReferenceLine] = Field(default_factory=list)
    drilldown_fields: list[str] = Field(default_factory=list)
    validation_expectations: WidgetValidationExpectations = Field(
        default_factory=WidgetValidationExpectations
    )
    priority_score: int = 0
    confidence_score: float = 0.0
    # Optional layout hints from the planner.
    gridX: int | None = None
    gridY: int | None = None
    gridW: int | None = None
    gridH: int | None = None


class DashboardSuggestion(BaseModel):
    title: str
    description: str = ""
    business_domain: str = ""
    intended_audience: str = ""
    executive_summary: str = ""
    widgets: list[DashboardWidgetSuggestion]


class SuggestDashboardResponse(BaseModel):
    suggestions: list[DashboardSuggestion]
    request_id: str
    model_used: str


class DashboardPlanWidget(BaseModel):
    """A widget outline within a dashboard plan, including renderable SQL.

    ``sql`` is grounded in the project's real tables so the platform can execute
    it and return real preview data for the Generate-tab dashboard previews.
    ``narrative_insight`` / risk / gap widgets carry an empty ``sql``.
    """

    title: str = ""
    chart_type: str = ""
    business_question: str = ""
    sql: str = ""
    label_column: str = ""
    value_column: str = ""


class DashboardPlanSuggestion(BaseModel):
    """A high-level dashboard plan the user can preview and choose to save."""

    title: str
    description: str = ""
    business_purpose: str = ""
    audience: str = ""
    widgets: list[DashboardPlanWidget] = Field(default_factory=list)
    kpis: list[str] = Field(default_factory=list)
    data_sources: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    quality_score: int = 0


class SuggestDashboardsMultiResponse(BaseModel):
    suggestions: list[DashboardPlanSuggestion]
    request_id: str
    model_used: str
