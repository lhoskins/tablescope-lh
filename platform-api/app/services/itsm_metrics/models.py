"""Shared data models for the ServiceNow ITSM metric engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

MetricKind = Literal["event_period", "snapshot_eom", "duration_period", "ratio_period"]
MetricStatus = Literal["measured", "calculated", "proxy", "not_implemented"]


@dataclass
class FilterSpec:
    column: str
    operator: str  # eq, neq, in, not_in, is_null, is_not_null, gt, gte, lt, lte
    value: Any | None = None


@dataclass
class MetricDefinition:
    key: str
    label: str
    dashboard: str
    order: int
    kind: MetricKind
    table: str
    date_field: str | None = None
    close_field: str | None = "resolved_at"  # for snapshot reconstruction
    state_field: str | None = None
    open_states: list[str] = field(default_factory=list)
    numerator: str | None = None
    denominator: str | None = None
    value_expression: str | None = None
    filters: list[FilterSpec] = field(default_factory=list)
    group_by: str | None = None
    aggregation: str = "count"  # count, sum, avg, min, max, distinct
    unit: str | None = None
    precision: int = 1
    polarity: str = "higher_is_better"  # higher_is_better, lower_is_better, neutral
    target: float | None = None
    status: MetricStatus = "measured"
    drill_down_dimensions: list[str] = field(default_factory=list)
    note: str | None = None


@dataclass
class PeriodBounds:
    start: str  # inclusive ISO date
    end: str  # inclusive ISO date
    label: str


@dataclass
class MetricValue:
    metric_key: str
    label: str
    value: float | None
    display_value: str
    period_start: str
    period_end: str
    previous_value: float | None = None
    delta: float | None = None
    delta_percent: float | None = None
    direction: str | None = None  # up, down, flat
    polarity: str = "higher_is_better"
    outcome: str | None = None  # favorable, unfavorable, neutral
    comparison_label: str | None = None
    status: MetricStatus = "measured"
    as_of: str | None = None


@dataclass
class ChartSeries:
    name: str
    x: list[str]
    y: list[float | None]


@dataclass
class ChartResult:
    chart_key: str
    title: str
    chart_type: str
    x_axis_label: str | None = None
    y_axis_label: str | None = None
    series: list[ChartSeries] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)


@dataclass
class DashboardResult:
    dashboard: str
    as_of: str
    filters: dict[str, Any]
    metrics: list[MetricValue]
    charts: list[ChartResult]
    data_quality: dict[str, Any]
