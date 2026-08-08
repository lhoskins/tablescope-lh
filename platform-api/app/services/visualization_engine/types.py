from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ChartType(StrEnum):
    """The renderable chart vocabulary.

    MUST stay in lockstep with ``WidgetType`` in
    ``web-ui/components/dashboard/types.ts`` and the ``ChartFamily`` union in
    ``web-ui/lib/visualizations/chartRegistry.ts``. ``tests/
    test_visualization_engine.py::test_chart_vocabulary_matches_frontend`` fails
    if they drift.
    """

    KPI = "kpi"
    TABLE = "table"
    LINE = "line"
    AREA = "area"
    BAR = "bar"
    COMBO = "combo"
    PIE = "pie"
    SCATTER = "scatter"
    EFFECT_SCATTER = "effect_scatter"
    RADAR = "radar"
    RADIAL_BAR = "radial_bar"
    TREEMAP = "treemap"
    SUNBURST = "sunburst"
    TREE = "tree"
    FUNNEL = "funnel"
    SANKEY = "sankey"
    GRAPH = "graph"
    PARALLEL = "parallel"
    LINES = "lines"
    HEATMAP = "heatmap"
    CANDLESTICK = "candlestick"
    BOXPLOT = "boxplot"
    PICTORIAL_BAR = "pictorial_bar"
    THEME_RIVER = "theme_river"
    GAUGE = "gauge"
    MAP = "map"

#: All renderable chart-type values (for validation / contract tests).
CHART_TYPES: frozenset[str] = frozenset(ct.value for ct in ChartType)

#: Value-format classes emitted alongside a decision (drives axis formatting).
ValueFormat = str  # "number" | "currency" | "percent" | "count"


@dataclass
class VizDecision:
    """The engine's output — one chart decision for a result set."""

    chart_type: ChartType
    chart_style: str = ""  # variant/subtype, e.g. "horizontal_bar", "donut"
    x_field: str | None = None
    y_field: str | None = None
    y2_field: str | None = None
    value_format: ValueFormat = "number"
    #: When set, the surface should rank rows by the measure (desc) and keep
    #: only the top ``top_n`` — a chart with too many categories is unreadable,
    #: so the engine caps it rather than plotting dozens of overlapping ticks.
    top_n: int | None = None
    reason: str = ""
    confidence: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "chartType": self.chart_type.value,
            "chartStyle": self.chart_style,
            "reason": self.reason,
            "confidence": round(self.confidence, 3),
            "valueFormat": self.value_format,
        }
        if self.x_field is not None:
            out["xField"] = self.x_field
        if self.y_field is not None:
            out["yField"] = self.y_field
        if self.chart_type == ChartType.KPI:
            # Surfaces that only look for metricField need the single metric too.
            out["metricField"] = self.y_field
        if self.y2_field is not None:
            out["y2Field"] = self.y2_field
        if self.top_n is not None:
            out["topN"] = self.top_n
        return out


@dataclass
class VizCandidate:
    """A ranked visualization candidate returned by ``recommend_visualizations``."""

    decision: VizDecision
    score: float = 0.0
    supported: bool = True
    unsupported_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.to_dict(),
            "score": round(self.score, 3),
            "supported": self.supported,
            "unsupportedReason": self.unsupported_reason,
        }


@dataclass
class _ColumnShape:
    name: str
    kind: str  # numeric | datetime | categorical | binary | period | text | empty
    cardinality: int
    period_like: bool


@dataclass
class _Shape:
    row_count: int
    columns: list[_ColumnShape]
    measures: list[str] = field(default_factory=list)  # numeric value columns
    dimensions: list[str] = field(default_factory=list)  # label/category columns
    time_columns: list[str] = field(default_factory=list)
