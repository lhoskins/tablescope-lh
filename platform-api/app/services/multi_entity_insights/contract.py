"""Typed multi-entity planning and insight contracts.

These Pydantic models express the analyst's plan and its lineage so the
workflow is auditable and deterministic. Runtime code is free to convert them
into plain dicts for the existing insight pipeline.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class SourceStrategy(BaseModel):
    preference: Literal["multi_source_first", "single_source_only"] = "multi_source_first"
    minimum_preferred_sources: int = 2
    allow_single_source_fallback: bool = True
    selected_source_count: int = 0
    fallback_used: bool = False
    fallback_reason_code: str | None = None
    fallback_reason: str | None = None
    candidates_evaluated: int = 0


class EntitySpec(BaseModel):
    type: str
    id_column: str
    name_column: str
    selection_mode: Literal["explicit", "top_n"] = "explicit"
    requested_names: list[str] = Field(default_factory=list)
    maximum_entities: int = 3

    @field_validator("maximum_entities")
    @classmethod
    def _cap_maximum(cls, v: int) -> int:
        return min(max(v, 2), 3)


class SourceSpec(BaseModel):
    table: str
    alias: str | None = None
    grain: list[str]
    measures: list[MeasureSpec | str | dict[str, Any]] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    filters: list[str] = Field(default_factory=list)

    @field_validator("measures", mode="before")
    @classmethod
    def _coerce_measures(cls, v: list[Any]) -> list[Any]:
        out: list[Any] = []
        for item in v:
            if isinstance(item, str):
                out.append({"name": item, "column": item, "aggregation": "sum"})
            elif isinstance(item, MeasureSpec):
                out.append(item.model_dump())
            else:
                out.append(item)
        return out


class RelationshipSpec(BaseModel):
    left_table: str
    right_table: str
    left_key: list[str]
    right_key: list[str]
    declared_cardinality: Literal["one_to_one", "one_to_many", "many_to_many"] = "one_to_many"
    observed_cardinality: Literal["one_to_one", "one_to_many", "many_to_many"] | None = None
    fanout_ratio: float | None = None
    unmatched_rate: float | None = None
    validation_status: Literal["valid", "valid_with_warnings", "rejected"] = "valid"
    rejection_reason: str | None = None


class TimeSpec(BaseModel):
    period_column: str | None = None
    period_grain: Literal["day", "week", "month", "quarter", "year"] = "month"
    start: str | None = None
    end: str | None = None
    relative_window: str | None = None


class MeasureSpec(BaseModel):
    name: str
    column: str
    table: str
    aggregation: Literal["sum", "avg", "count", "min", "max"] = "sum"
    format: Literal["number", "currency", "percent", "count"] = "number"
    numerator_column: str | None = None
    denominator_column: str | None = None
    derived_expression: str | None = None
    owner_table: str | None = None


class MethodRef(BaseModel):
    method_id: str
    intent: str = "compare_entities"
    role: Literal["primary", "supporting"] = "supporting"
    reason: str | None = None


class MethodBundle(BaseModel):
    primary: MethodRef
    supporting: list[MethodRef] = Field(default_factory=list, max_length=2)


class MultiEntityPlan(BaseModel):
    contract_version: int = 1
    analysis_id: str
    intent: Literal[
        "compare_entities",
        "compare_entities_across_domains",
        "entity_contribution_to_change",
        "cross_entity_relationship",
        "compare_entity_trends",
    ]
    title: str
    business_question: str
    source_strategy: SourceStrategy
    entity: EntitySpec
    sources: list[SourceSpec]
    relationships: list[RelationshipSpec]
    time: TimeSpec
    final_grain: list[str]
    measures: list[MeasureSpec]
    method_bundle: MethodBundle

    @model_validator(mode="after")
    def _validate_source_count_and_entities(self) -> MultiEntityPlan:
        if len(self.sources) < 1:
            raise ValueError("At least one source table is required")
        if self.entity.selection_mode == "explicit" and len(self.entity.requested_names) < 2:
            raise ValueError("At least two explicit entity names are required for explicit-mode analysis")
        if len(self.entity.requested_names) > 3:
            raise ValueError("At most three entity names are supported")
        missing = [s for s in self.sources if not s.grain]
        if missing:
            raise ValueError("Every source must declare its grain")
        return self


class JoinValidationResult(BaseModel):
    status: Literal["valid", "valid_with_warnings", "rejected"]
    reason: str | None = None
    observed_cardinality: Literal["one_to_one", "one_to_many", "many_to_many"] | None = None
    fanout_ratio: float | None = None
    unmatched_rate: float | None = None
    left_row_count: int | None = None
    right_row_count: int | None = None
    left_key_distinct: int | None = None
    right_key_distinct: int | None = None
    duplicates_on_one_side: int | None = None


class FrameValidationResult(BaseModel):
    status: Literal["valid", "valid_with_warnings", "rejected"]
    entity_count: int
    period_count: int | None = None
    duplicate_grain_rows: int = 0
    missing_requested_entities: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    reason: str | None = None


class ExecutionEnvelope(BaseModel):
    method_id: str
    intent: str = ""
    roles: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    envelope: dict[str, Any] = Field(default_factory=dict)
    status: str | None = None


class EvidenceSynthesis(BaseModel):
    status: Literal["supported", "partially_supported", "conflicting", "insufficient_data"]
    summary: str
    confidence: Literal["low", "medium", "high"] = "medium"
    method_statuses: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class SourceLineage(BaseModel):
    table_id: str
    display_name: str
    columns: list[str]
    source_project_id: int | None = None
    source_type: Literal["table", "view", "query"] = "table"


class JoinLineage(BaseModel):
    left: str
    right: str
    declared_cardinality: str
    observed_cardinality: str | None = None
    fanout_ratio: float | None = None
    unmatched_rate: float | None = None
    validation_status: str


class InsightLineage(BaseModel):
    lineage_version: int = 1
    source_strategy: SourceStrategy
    sources: list[SourceLineage]
    joins: list[JoinLineage]
    grain: dict[str, Any]
    filters: list[str]
    aggregations: list[dict[str, Any]]
    resolved_entities: list[dict[str, Any]]
    query_hash: str
    query_version: int = 1
    executions: dict[str, Any]
    validation: dict[str, Any]


class MultiEntityInsightPayload(BaseModel):
    """Compact payload that a card builder can turn into an InsightCard dict."""

    insight_type: str = "multi_entity_compare"
    severity: str = "info"
    title: str
    summary: str
    business_question: str
    chart: dict[str, Any] | None = None
    tables: list[str]
    sql: str | None = None
    method_envelope: dict[str, Any] | None = None
    supporting_envelopes: list[dict[str, Any]] = Field(default_factory=list)
    lineage: InsightLineage
    evidence_status: str = "supported"
    entities: list[dict[str, Any]]
    entity_type: str
    source_strategy: SourceStrategy
    fallback_reason: str | None = None
    warnings: list[str] = Field(default_factory=list)
