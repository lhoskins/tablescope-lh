"""Universal Visualization Engine (M2).

A single, deterministic, LLM-free decision function that maps a result set's
*shape* to a chart type drawn from the one vocabulary the frontend can actually
render — the 13 ``WidgetType`` families in ``web-ui/lib/visualizations/
chartRegistry.ts`` (mirrored by :class:`ChartType` below).

Before this engine, chart selection lived in four mutually-inconsistent places
with four different vocabularies (``ai_proxy._suggest_visualization``,
``home_intelligence._build_chart``/``_CHART_ALIASES``, the ``WidgetRenderer``
switch, and an LLM prompt in ``ai-server`` that named types nothing could draw).
This module is the single authority all of those call sites delegate to, so the
same input shape yields the same chart everywhere.

Design rules (Devin ASK §10, plan §5):
- Pure function, no LLM call, no DB. Same input -> same output.
- Output ``chartType`` is *always* a real renderable family (fail to ``table``).
- The strongest existing heuristic (``home_intelligence``: period->line,
  part-of-whole->donut, id-labels->horizontal bar, single-row->kpi,
  two-numeric->scatter/combo, currency/percent/count format detection) is the
  seed, generalized here rather than discarded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ChartType(str, Enum):
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
    RADAR = "radar"
    RADIAL_BAR = "radial_bar"
    TREEMAP = "treemap"
    FUNNEL = "funnel"
    SANKEY = "sankey"


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


# ── Shape detection (lightweight, dependency-free) ───────────────────────────
# The engine derives just enough shape to decide a chart. When the caller
# already has the M1 statistical profiler output, it can pass it via
# ``profile=`` and we reuse its column kinds; otherwise we classify here so a
# pure chart decision never pays for scipy/normality computation.

_PERIOD_LABEL_RE = re.compile(
    r"(?i)^\s*("
    r"\d{4}"  # 2026
    r"|\d{4}[-/]\d{1,2}([-/]\d{1,2})?"  # 2026-01, 2026/01/15
    r"|q[1-4][\s-]?\d{2,4}"  # Q1 2026
    r"|(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?[\s-]?\d{0,4}"
    r"|(week|wk|day)\s?\d+"
    r")\s*$"
)
_PERIOD_COL_RE = re.compile(
    r"(?i)\b(period|month|year|quarter|week|date|day|fiscal|time)\b"
)
_SHARE_LABEL_KEYS = (
    "categor", "type", "status", "segment", "region", "channel", "class",
    "group", "tier", "rating", "priority", "department", "mode", "method",
    "reason", "country", "state", "industry",
)
_ID_LABEL_RE = re.compile(
    r"(?i)(sup|sku|id|code|part|item|vendor|customer|prod)[-_ ]?\w*\d"
)
_PCT_COL_RE = re.compile(
    r"(?i)\b(rate|pct|percent|percentage|ratio|share|on[_ -]?time|utiliz\w*|"
    r"defect[_ ]?rate|yield|compliance)\b"
)
_CURRENCY_COL_RE = re.compile(
    r"(?i)\b(revenue|cost|spend|spending|price|amount|sales|value|budget|usd|"
    r"dollars?)\b"
)
_COUNT_COL_RE = re.compile(
    r"(?i)\b(count|qty|quantity|units?|number|orders?|shipments?|items?|"
    r"records?|inspections?|defects?)\b"
)

#: Above this many distinct categories (or when labels are id-like) a vertical
#: bar's x-axis ticks overlap, so the engine flips it to a horizontal bar whose
#: category labels stack readably down the y-axis.
_HORIZONTAL_BAR_THRESHOLD = 5
#: A bar with more categories than this is ranked by the measure and capped to
#: the top N — dozens of bars are unreadable and bury the story; the surface
#: still shows the full result in its data table beneath the chart.
_BAR_RANK_CAP = 12


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        s = value.strip().replace(",", "").replace("$", "").replace("%", "")
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


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


def _rows_as_dicts(columns: list[str], rows: list[Any]) -> list[dict[str, Any]]:
    if rows and isinstance(rows[0], dict):
        return list(rows)
    return [dict(zip(columns, r, strict=False)) for r in rows]


def _column_values(rows: list[dict[str, Any]], col: str, limit: int = 50) -> list[Any]:
    out: list[Any] = []
    for r in rows[:limit]:
        v = r.get(col)
        if v is not None and v != "":
            out.append(v)
    return out


def _classify_column(
    name: str, values: list[Any], profile_kind: str | None
) -> _ColumnShape:
    non_null = values
    if not non_null:
        return _ColumnShape(name, "empty", 0, False)
    cardinality = len({str(v) for v in non_null})
    numeric_hits = sum(1 for v in non_null if _to_float(v) is not None)
    numeric_rate = numeric_hits / len(non_null)

    period_col = bool(_PERIOD_COL_RE.search(name))
    str_vals = [str(v) for v in non_null]
    period_vals = (
        len(str_vals) >= 3
        and sum(1 for v in str_vals if _PERIOD_LABEL_RE.match(v))
        >= max(3, int(len(str_vals) * 0.6))
    )
    period_like = period_col or period_vals

    # Numeric years (2020, 2021, ...) read as a time dimension, not a measure.
    if numeric_rate >= 0.9 and period_like:
        return _ColumnShape(name, "period", cardinality, True)

    if profile_kind in ("numeric", "binary", "datetime", "categorical"):
        kind = "period" if (profile_kind == "datetime" or period_like) else profile_kind
        return _ColumnShape(name, kind, cardinality, period_like)

    if numeric_rate >= 0.9:
        uniq_numeric = len({_to_float(v) for v in non_null if _to_float(v) is not None})
        kind = "binary" if uniq_numeric <= 2 else "numeric"
        return _ColumnShape(name, kind, cardinality, period_like)
    if period_like:
        return _ColumnShape(name, "period", cardinality, True)
    if cardinality <= max(2, int(0.6 * len(non_null))):
        return _ColumnShape(name, "categorical", cardinality, False)
    return _ColumnShape(name, "text", cardinality, False)


def derive_shape(
    columns: list[str],
    rows: list[Any],
    profile: dict[str, Any] | None = None,
) -> _Shape:
    """Classify columns into measures / dimensions / time columns.

    When ``profile`` (the M1 data-profiler output) is provided we honour its
    column ``kind`` classification, so the Method Engine and Visualization Engine
    agree on the shape of the same result set.
    """
    dict_rows = _rows_as_dicts(columns, rows)
    profile_cols = (profile or {}).get("columns", {}) if profile else {}
    shapes: list[_ColumnShape] = []
    for col in columns:
        pk = None
        if col in profile_cols and isinstance(profile_cols[col], dict):
            pk = profile_cols[col].get("kind")
        shapes.append(_classify_column(col, _column_values(dict_rows, col), pk))

    measures = [c.name for c in shapes if c.kind in ("numeric", "binary")]
    time_columns = [c.name for c in shapes if c.kind == "period"]
    dimensions = [
        c.name for c in shapes if c.kind in ("categorical", "text", "period")
    ]
    return _Shape(
        row_count=len(dict_rows),
        columns=shapes,
        measures=measures,
        dimensions=dimensions,
        time_columns=time_columns,
    )


def detect_value_format(name: str, values: list[Any]) -> ValueFormat:
    """Classify a metric's display format from its name + values."""
    # Treat snake_case as words so ``total_revenue`` matches ``revenue`` etc.
    label = (name or "").replace("_", " ")
    if _PCT_COL_RE.search(label):
        return "percent"
    if _CURRENCY_COL_RE.search(label):
        return "currency"
    if _COUNT_COL_RE.search(label):
        return "count"
    nums = [f for v in values if (f := _to_float(v)) is not None]
    if nums and all(0.0 <= v <= 1.0 for v in nums) and any(
        v not in (0.0, 1.0) for v in nums
    ):
        return "percent"
    return "number"


def _categorical_bar(
    label_col: str,
    value_col: str,
    vfmt: ValueFormat,
    label_card: int,
    labels: list[str],
    *,
    confidence: float,
) -> VizDecision:
    """Bar decision for a category comparison, made readable for many categories.

    Many distinct or id-like categories flip to a horizontal bar (labels stack
    down the y-axis); beyond :data:`_BAR_RANK_CAP` the decision also asks the
    surface to rank by the measure and keep only the top N, so the chart shows
    the leaders instead of an unreadable wall of ticks.
    """
    many = label_card > _HORIZONTAL_BAR_THRESHOLD or _looks_like_id_labels(labels)
    top_n = _BAR_RANK_CAP if label_card > _BAR_RANK_CAP else None
    if top_n is not None:
        reason = (
            f"{label_card} categories — ranked top {top_n} as a horizontal bar "
            "so the axis stays readable."
        )
    elif many:
        reason = "Several categories — horizontal bar for readable labels."
    else:
        reason = "Category comparison."
    return VizDecision(
        ChartType.BAR,
        chart_style="horizontal_bar" if many else "",
        x_field=label_col,
        y_field=value_col,
        value_format=vfmt,
        top_n=top_n,
        reason=reason,
        confidence=confidence,
    )


def _looks_like_share(label_col: str, cardinality: int, all_positive: bool) -> bool:
    if not (3 <= cardinality <= 8) or not all_positive:
        return False
    return any(k in (label_col or "").lower() for k in _SHARE_LABEL_KEYS)


def _looks_like_id_labels(labels: list[str]) -> bool:
    if not labels:
        return False
    idish = sum(
        1
        for lbl in labels
        if _ID_LABEL_RE.search(lbl) or len(lbl) >= 12 or any(c.isdigit() for c in lbl)
    )
    return idish >= max(1, int(len(labels) * 0.5))


# ── The decision function ────────────────────────────────────────────────────

def select_visualization(
    columns: list[str],
    rows: list[Any],
    *,
    profile: dict[str, Any] | None = None,
    intent_hint: str | None = None,
) -> VizDecision:
    """Choose the best renderable chart for a result set (deterministic).

    ``intent_hint`` is an optional caller-supplied preference (e.g. a planner's
    chart hint, or an LLM's ``analysisIntent``). It is honoured only when it
    names a real family *and* the data shape supports it — the data always wins,
    so the engine never emits something the renderer cannot draw.
    """
    if not columns or not rows:
        return VizDecision(ChartType.TABLE, reason="No data to plot.", confidence=1.0)

    dict_rows = _rows_as_dicts(columns, rows)
    shape = derive_shape(columns, dict_rows, profile)
    hint = _normalize_hint(intent_hint)

    # 1) A single row with no dimension to plot is a scalar summary -> KPI tile.
    #    (A single row that still carries a real dimension — e.g. one supplier or
    #    one month — keeps its labeled context and flows to the bar/line logic.)
    if shape.row_count == 1 and not shape.dimensions:
        metric = shape.measures[0] if shape.measures else None
        if metric:
            return VizDecision(
                ChartType.KPI,
                x_field=None,
                y_field=metric,
                value_format=detect_value_format(
                    metric, _column_values(dict_rows, metric)
                ),
                reason="Single-row scalar summary — headline metric as a KPI tile.",
                confidence=0.9,
            )
        return VizDecision(
            ChartType.TABLE, reason="Single row with no numeric metric.", confidence=0.7
        )

    if not shape.measures:
        return VizDecision(
            ChartType.TABLE,
            reason="No numeric measure to plot — showing detail rows.",
            confidence=0.9,
        )

    label_col = _primary_dimension(shape)
    value_col = shape.measures[0]
    values = _column_values(dict_rows, value_col, limit=200)
    vfmt = detect_value_format(value_col, values)

    # 2) Correlation of two measures with no meaningful dimension -> scatter.
    if len(shape.measures) >= 2 and (
        hint == "scatter" or label_col is None
    ):
        return VizDecision(
            ChartType.SCATTER,
            x_field=shape.measures[0],
            y_field=shape.measures[1],
            value_format=vfmt,
            reason="Two numeric measures with no category — correlation scatter.",
            confidence=0.7,
        )

    # 3) Time series -> line (trend). Two measures over time -> combo.
    is_time = bool(shape.time_columns) or (
        label_col is not None and _is_period_dimension(shape, label_col)
    )
    if is_time:
        x = shape.time_columns[0] if shape.time_columns else label_col
        if len(shape.measures) >= 2 and hint in (None, "line", "combo", "area"):
            return VizDecision(
                ChartType.COMBO,
                chart_style="bar_line",
                x_field=x,
                y_field=shape.measures[0],
                y2_field=shape.measures[1],
                value_format=vfmt,
                reason="Two metrics over a shared time axis — combo (bar + line).",
                confidence=0.75,
            )
        chart = ChartType.AREA if hint == "area" else ChartType.LINE
        return VizDecision(
            chart,
            x_field=x,
            y_field=value_col,
            value_format=vfmt,
            reason="Ordered time-period labels — trend over time.",
            confidence=0.85,
        )

    # 4) Honour a valid explicit hint the shape supports.
    all_positive = all((f := _to_float(v)) is None or f >= 0 for v in values)
    label_card = _dimension_cardinality(shape, label_col)
    forced = _hint_if_supported(
        hint, shape, label_col, value_col, vfmt, label_card, all_positive
    )
    if forced is not None:
        return forced

    # 5) Part-of-a-whole -> pie/donut.
    if label_col is not None and _looks_like_share(label_col, label_card, all_positive):
        return VizDecision(
            ChartType.PIE,
            chart_style="donut",
            x_field=label_col,
            y_field=value_col,
            value_format=vfmt,
            reason="A few positive categories of a whole — share breakdown.",
            confidence=0.7,
        )

    # 6) Categorical comparison -> bar. Many/id-like categories rank + cap and go
    #    horizontal so the axis stays readable (see ``_categorical_bar``).
    if label_col is not None:
        labels = [str(v) for v in _column_values(dict_rows, label_col, limit=50)]
        return _categorical_bar(
            label_col, value_col, vfmt, label_card, labels, confidence=0.65
        )

    # 7) Fallback.
    return VizDecision(
        ChartType.TABLE, reason="No clear chart shape — showing detail rows.",
        confidence=0.6,
    )


# ── Hint handling ────────────────────────────────────────────────────────────
# Map the legacy planner / LLM vocabularies (which named types nothing could
# render) down to real families, so an upstream hint never forces an
# unrenderable output.

_HINT_ALIASES: dict[str, str] = {
    "bar": "bar",
    "column": "bar",
    "vertical_bar": "bar",
    "horizontal_bar": "bar",
    "stacked_bar": "bar",
    "grouped_bar": "bar",
    "waterfall": "bar",
    "heatmap": "bar",
    "line": "line",
    "multi_line": "line",
    "smooth_line": "line",
    "step_line": "line",
    "sparkline_table": "line",
    "dual_line": "combo",
    "combo": "combo",
    "composed": "combo",
    "area": "area",
    "pie": "pie",
    "donut": "pie",
    "scatter": "scatter",
    "bubble": "scatter",
    "radar": "radar",
    "radial_bar": "radial_bar",
    "gauge": "radial_bar",
    "bullet": "radial_bar",
    "treemap": "treemap",
    "funnel": "funnel",
    "sankey": "sankey",
    "kpi": "kpi",
    "kpi_grid": "kpi",
    "table": "table",
    "pivot_table": "table",
    "narrative_insight": "table",
    "none": "table",
    "text": "table",
    "callout": "table",
}


def normalize_chart_hint(raw: str | None) -> str | None:
    """Public: map any legacy chart name to a renderable family (or ``None``)."""
    return _normalize_hint(raw)


def _normalize_hint(raw: str | None) -> str | None:
    if not raw:
        return None
    key = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
    return _HINT_ALIASES.get(key)


def _hint_if_supported(
    hint: str | None,
    shape: _Shape,
    label_col: str | None,
    value_col: str,
    vfmt: ValueFormat,
    label_card: int,
    all_positive: bool,
) -> VizDecision | None:
    """Return a decision for an explicit hint when the shape supports it.

    Trend families (``line``/``area``/``combo``) and ``scatter`` are resolved by
    the shape/time logic in the main flow, not forced by a hint — so a ``line``
    hint on non-time data still corrects to a category chart. ``kpi``/``table``
    are shape decisions, not honoured as hints.
    """
    if hint is None or hint in ("line", "area", "combo", "scatter", "kpi", "table"):
        return None
    # Honour a pie/donut request only when the shape is a genuine part-of-whole
    # (a few positive slices); otherwise fall through so an oversized/negative
    # "pie" corrects to a ranking bar.
    if hint == "pie" and label_col is not None and all_positive and 2 <= label_card <= 8:
        return VizDecision(
            ChartType.PIE, chart_style="donut", x_field=label_col, y_field=value_col,
            value_format=vfmt, reason="Explicit share breakdown.", confidence=0.6,
        )
    if hint in ("radar", "treemap", "funnel", "sankey", "radial_bar") and (
        label_col is not None
    ):
        return VizDecision(
            ChartType(hint), x_field=label_col, y_field=value_col,
            value_format=vfmt, reason=f"Explicit {hint} request.", confidence=0.55,
        )
    if hint == "bar" and label_col is not None:
        # The hint path only carries the shape (not raw label values), so
        # id-like detection is skipped here; the cardinality rule still ranks
        # and flips many-category bars to horizontal.
        return _categorical_bar(
            label_col, value_col, vfmt, label_card, [], confidence=0.6
        )
    return None


# ── Shape helpers ────────────────────────────────────────────────────────────

def _primary_dimension(shape: _Shape) -> str | None:
    """Pick the best label column: prefer a time column, then a categorical."""
    if shape.time_columns:
        return shape.time_columns[0]
    for c in shape.columns:
        if c.kind in ("categorical", "text"):
            return c.name
    return None


def _is_period_dimension(shape: _Shape, col: str) -> bool:
    return any(c.name == col and c.period_like for c in shape.columns)


def _dimension_cardinality(shape: _Shape, col: str | None) -> int:
    if col is None:
        return 0
    for c in shape.columns:
        if c.name == col:
            return c.cardinality
    return 0
