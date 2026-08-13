"""Schemas for the intelligence pipeline: plan, SQL repair, interpretation."""

from pydantic import BaseModel, Field

from .common import AIBaseRequest


class PlannedAnalysis(BaseModel):
    id: str
    category: str = "trend"  # risk | trend | opportunity | relationship
    title: str = ""
    rationale: str = ""
    sql: str = ""
    chart_type: str = "bar"  # see _ALLOWED_PLAN_CHART_TYPES in routers/ai.py
    label_column: str = ""
    value_column: str = ""
    # Second metric used by dual_line/scatter/bubble/heatmap (color) and as the
    # target for gauge/bullet. Empty for single-metric charts.
    value_column_2: str = ""
    severity_hint: str = "watch"
    source_documents: list[str] = Field(default_factory=list)


class FirstPassResult(BaseModel):
    """A single first-pass analysis and its real result, sent back to the
    planner so the model can propose deeper, evidence-based follow-ups."""

    analysis: PlannedAnalysis
    row_count: int = 0
    columns: list[str] = Field(default_factory=list)
    rows: list[dict] = Field(default_factory=list)
    error: str = ""


class IntelligencePlanRequest(AIBaseRequest):
    """Ask the LLM to propose high-value diagnostic analyses for a project.

    The model acts as a senior analyst: given only the project's real schema
    and document summaries, it proposes the analyses a well-run company would
    run, writing the SQL in memory. No metric is hard-coded by the caller.
    """
    allowed_tables: list[str] = Field(default_factory=list)
    # Exact schema so the LLM never invents columns:
    # [{"table": <view>, "columns": [{"name": <col>, "type": <type>}]}]
    table_schema: list[dict] = Field(default_factory=list)
    documents: list[dict] = Field(default_factory=list)  # [{title, summary, tags}]
    # Evidence-backed join candidates the platform discovered from scope
    # metadata / matching keys. Each: {left_table, right_table, left_join_key,
    # right_join_key, relationship_type, join_confidence, confidence_reason,
    # row_multiplication_risk}. The planner may only propose multi-table
    # analyses that are supported by one of these hints.
    relationship_hints: list[dict] = Field(default_factory=list)
    reference_kpis: list[dict] = Field(default_factory=list)
    max_analyses: int = 6
    # 1 = executive/high-level (few, most leveraging) .. 5 = granular (many, detailed)
    granularity: int = 3
    project_context: dict = Field(default_factory=dict)
    # Compact Knowledge Graph digest from the platform (risks, gaps,
    # opportunities, warnings, recommended KPIs). Injected into the plan
    # prompt as HYPOTHESES the planner should validate/quantify/refute with
    # SQL — never asserted as findings without a query result behind them.
    knowledge_graph_context: dict = Field(default_factory=dict)
    # Results from an earlier planning/execution pass. When present the
    # planner is asked to go deeper — explain root causes, surface anomalies,
    # and propose cross-cutting follow-up analyses.
    first_pass: list[FirstPassResult] = Field(default_factory=list)


class IntelligencePlanResponse(BaseModel):
    analyses: list[PlannedAnalysis] = Field(default_factory=list)
    request_id: str = ""
    model_used: str = ""


class IntelligenceFixSQLRequest(AIBaseRequest):
    """Repair a query that the Teiid engine rejected.

    Given the failing SQL, the engine's error message, and the exact schema,
    the model returns a corrected single-table query (or empty if unfixable).
    """
    sql: str = ""
    error: str = ""
    allowed_tables: list[str] = Field(default_factory=list)
    table_schema: list[dict] = Field(default_factory=list)


class IntelligenceFixSQLResponse(BaseModel):
    sql: str = ""
    request_id: str = ""
    model_used: str = ""


class InterpretAnalysisInput(BaseModel):
    id: str
    category: str = "trend"
    title: str = ""
    rationale: str = ""
    chart_type: str = "bar"
    columns: list[str] = Field(default_factory=list)
    rows: list[dict] = Field(default_factory=list)  # small sample of result rows
    row_count: int = 0
    document_context: str = ""  # for document-driven analyses


class IntelligenceInterpretRequest(AIBaseRequest):
    """Turn executed query results (or document context) into business prose."""
    analyses: list[InterpretAnalysisInput] = Field(default_factory=list)
    project_context: dict = Field(default_factory=dict)


class InterpretedInsight(BaseModel):
    id: str
    title: str = ""
    summary: str = ""
    severity: str = "info"  # critical | urgent | watch | opportunity | info
    callout_type: str = ""  # risk | opportunity | info | ""
    callout_text: str = ""
    recommendation: str = ""


class IntelligenceInterpretResponse(BaseModel):
    insights: list[InterpretedInsight] = Field(default_factory=list)
    request_id: str = ""
    model_used: str = ""
