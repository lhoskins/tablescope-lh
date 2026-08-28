"""Schemas for the intelligence pipeline: plan, SQL repair, interpretation."""

from pydantic import BaseModel, Field

from .common import AIBaseRequest
from .query import SourceCatalogEntry


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


class RepairSQLColumnKnowledge(BaseModel):
    """One column's real sample value/type, revealed to the repair agent
    because it asked for that specific column via an ``inspect_column`` step."""

    table: str = ""
    column: str = ""
    sample: str = ""
    type: str = ""


class IntelligenceRepairSQLStepRequest(AIBaseRequest):
    """One decision step in the SQL self-repair agent loop.

    Rather than a single blind full-query rewrite, this returns ONE of three
    actions: rewrite the query directly, ask to see a specific column's real
    sample value/type before deciding, or give up. The caller (platform-api)
    executes the chosen action and, for ``inspect_column``, calls this
    endpoint again with the revealed column appended to ``known_columns`` --
    so the model only pays for the schema detail it actually asks for,
    instead of every column of every allowed table being crammed into the
    prompt on every attempt regardless of relevance.
    """

    sql: str = ""
    error: str = ""
    allowed_tables: list[str] = Field(default_factory=list)
    table_schema: list[dict] = Field(default_factory=list)
    known_columns: list[RepairSQLColumnKnowledge] = Field(default_factory=list)


class IntelligenceRepairSQLStepResponse(BaseModel):
    action: str = "give_up"  # "rewrite" | "inspect_column" | "give_up"
    sql: str = ""
    table: str = ""
    column: str = ""
    request_id: str = ""
    model_used: str = ""


class InvestigationStepResult(BaseModel):
    """One completed sub-query in a multi-step investigation, summarized for
    the next decision -- a bounded preview, not the full row set, so the
    prompt stays scoped as the investigation grows."""

    sub_question: str = ""
    sql: str = ""
    columns: list[str] = Field(default_factory=list)
    row_count: int = 0
    sample_rows: list[dict] = Field(default_factory=list)
    error: str = ""


class IntelligenceInvestigateStepRequest(AIBaseRequest):
    """One decision step in the multi-query "why" investigation agent.

    Given the original question and every sub-query run so far, decide
    whether to run one more targeted sub-question or stop because enough
    evidence has been gathered. Each sub-query itself is generated and
    executed by the existing ask-and-run pipeline -- this endpoint only
    plans which question to ask next, it never writes or sees SQL directly
    beyond the bounded summary in ``steps``.
    """

    question: str = ""
    steps: list[InvestigationStepResult] = Field(default_factory=list)
    steps_remaining: int = 0
    # The same source catalog SQL generation uses (name/columns/description,
    # plus a profile summary of row count, date range, and categorical
    # values per source), so the planner only proposes sub-questions about
    # columns that actually exist and can tell when the data can't support a
    # "trend" at all -- instead of reasoning from the bare question text.
    source_catalog: list[SourceCatalogEntry] = Field(default_factory=list)


class IntelligenceInvestigateStepResponse(BaseModel):
    action: str = "finish"  # "query" | "finish"
    sub_question: str = ""
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
