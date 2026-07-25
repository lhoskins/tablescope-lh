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
from enum import StrEnum
from typing import Any, cast

from app.services.chart_catalog import (
    ShapeFacts,
    ShapeSummary,
    fit_ranked,
)


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
_METRIC_LABEL_KEYS = (
    "metric", "measure", "name", "label", "kpi", "indicator", "stat",
    "title", "description", "field",
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


def _looks_like_metric_label(label_col: str | None) -> bool:
    if not label_col:
        return False
    lower = label_col.lower()
    return any(k in lower for k in _METRIC_LABEL_KEYS)


# The public single-decision entry point is select_visualization(), defined
# below after the richer recommend_visualizations() candidate builder.


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
    "heatmap": "heatmap",
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
    "gauge": "gauge",
    "bullet": "gauge",
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


def _cardinality(shape: _Shape, col: str) -> int:
    """Return the stored cardinality for a known column."""
    for c in shape.columns:
        if c.name == col:
            return c.cardinality
    return 0


def _has_negative(rows: list[dict[str, Any]], col: str) -> bool:
    for r in rows:
        v = _to_float(r.get(col))
        if v is not None and v < 0:
            return True
    return False


def _has_ohlc_roles(roles: dict[str, Any]) -> bool:
    return all(roles.get(k) for k in ("open", "high", "low", "close"))


def _looks_hierarchical(rows: list[dict[str, Any]], dims: list[str]) -> bool:
    """True when the first two dimensions look like a parent/child hierarchy."""
    if len(dims) < 2:
        return False
    parent_col, child_col = dims[0], dims[1]
    parent_for_child: dict[str, str] = {}
    parent_counts: dict[str, int] = {}
    for r in rows:
        parent = str(r.get(parent_col, ""))
        child = str(r.get(child_col, ""))
        if not parent or not child:
            continue
        if child in parent_for_child and parent_for_child[child] != parent:
            return False
        parent_for_child[child] = parent
        parent_counts[parent] = parent_counts.get(parent, 0) + 1
    # Need multiple parents and at least one parent with multiple children.
    return len(parent_counts) >= 2 and any(c > 1 for c in parent_counts.values())


def _catalog_shape(
    shape: _Shape,
    dict_rows: list[dict[str, Any]],
    roles: dict[str, Any],
) -> ShapeSummary:
    """Map the engine's detailed shape to the markdown catalog's summary."""
    dims = [c for c in shape.dimensions if not _is_period_dimension(shape, c)]
    traits: set[str] = set()
    if shape.time_columns:
        traits.add("time")
    if shape.dimensions and not dims:
        traits.add("period_only_dimension")
    if shape.row_count == 1 and not shape.dimensions:
        traits.add("single_row")
    if roles.get("rate"):
        traits.add("rate")
    if roles.get("source") and roles.get("target"):
        traits.add("flow")
    if roles.get("group") or roles.get("parent") or (
        len(dims) >= 2 and _looks_hierarchical(dict_rows, dims)
    ):
        traits.add("hierarchy")
    if _has_ohlc_roles(roles):
        traits.add("ohlc")

    # Stage/ordered trait for funnel: a single non-period dimension that is
    # explicitly tagged as a stage, with at least one measure to size stages.
    stage_col = roles.get("stage")
    if stage_col and stage_col in dims and shape.measures:
        traits.add("stage")

    max_dim_card = max((_cardinality(shape, d) for d in dims), default=1)
    if shape.row_count >= max(15, 2 * max_dim_card) and "period_only_dimension" not in traits:
        traits.add("raw")
    if any(_has_negative(dict_rows, m) for m in shape.measures):
        traits.add("negative_values")
    return ShapeSummary(dims=len(dims), measures=len(shape.measures), traits=frozenset(traits))


#: Below this fit confidence no chart explains the data, so the detail table
#: is promoted instead of showing the least-bad chart.
_WEAK_FIT_THRESHOLD = 0.25

#: Catalog families that render through a parent ``ChartType`` plus a style
#: variant rather than having their own enum member. Mirrors the frontend
#: lockstep map in ``web-ui/lib/visualizations/chartCatalogLockstep.test.ts``.
_CATALOG_SUBTYPE_PARENTS: dict[str, tuple[str, str]] = {
    "histogram": ("BAR", "histogram"),
    "waterfall": ("BAR", "waterfall"),
    "bubble": ("SCATTER", "bubble"),
    "bump": ("LINE", "bump"),
    "calendar_heatmap": ("HEATMAP", "calendar"),
}


def _catalog_chart_type(family: str) -> tuple[Any, str] | None:
    """Resolve a catalog family to a (ChartType, chart_style) pair, or None."""
    direct = getattr(ChartType, family.upper().replace("-", "_"), None)
    if direct is not None:
        return direct, ""
    parent = _CATALOG_SUBTYPE_PARENTS.get(family)
    if parent is None:
        return None
    chart_type = getattr(ChartType, parent[0], None)
    return (chart_type, parent[1]) if chart_type is not None else None


def _catalog_facts(shape: _Shape, dict_rows: list[dict[str, Any]]) -> ShapeFacts:
    """Per-dataset facts (row count, dimension cardinalities) for fit scoring.

    Cardinalities are counted over the full result rows rather than reusing
    ``_ColumnShape.cardinality``, which saturates at the shape sampler's limit —
    an id-like column with 300 distinct values would otherwise look like 50 and
    escape the "too many categories" penalty.

    Ordered with the primary dimension first so a family's ``ideal_dim_card`` /
    ``ideal_dim2_card`` hints line up with the axes it would actually use.
    """
    dims = [c for c in shape.dimensions if not _is_period_dimension(shape, c)]
    primary = _primary_dimension(shape)
    if primary in dims:
        dims = [primary] + [d for d in dims if d != primary]

    cardinalities: list[int] = []
    for d in dims:
        try:
            cardinalities.append(len({str(r.get(d)) for r in dict_rows if r.get(d) is not None}))
        except TypeError:  # unhashable cell value — fall back to the sampled count
            cardinalities.append(_cardinality(shape, d))
    return ShapeFacts(row_count=shape.row_count, dim_cardinalities=tuple(cardinalities))


def _detect_semantic_roles(
    columns: list[str], rows: list[dict[str, Any]]
) -> dict[str, str | None]:
    """Infer source/target/value/group/stage/rate roles from column names and data.

    Roles are hints for richer families (sankey, treemap, funnel, radial_bar,
    radar). They never force an unrenderable chart; the shape still wins.
    """
    roles: dict[str, str | None] = {
        "source": None,
        "target": None,
        "value": None,
        "group": None,
        "stage": None,
        "rate": None,
    }
    lower = {c.lower(): c for c in columns}

    # Source / target / value triad for Sankey.
    for key in ("source", "from", "origin", "src"):
        if key in lower:
            roles["source"] = lower[key]
            break
    for key in ("target", "to", "destination", "dst", "dest"):
        if key in lower:
            roles["target"] = lower[key]
            break
    for key in ("value", "weight", "amount", "flow", "volume"):
        if key in lower:
            roles["value"] = lower[key]
            break

    # Stage column for funnel.
    stage_re = re.compile(r"(stage|step|phase|status|pipeline|funnel)", re.I)
    for c in columns:
        if stage_re.search(c):
            roles["stage"] = c
            break

    # Group / parent for treemap.
    group_re = re.compile(r"(group|category|class|type|segment|region|department|parent)", re.I)
    for c in columns:
        if group_re.search(c) and c != roles.get("source") and c != roles.get("target"):
            roles["group"] = c
            break

    # Rate / percent column for radial bar.
    rate_re = re.compile(r"(rate|pct|percent|percentage|ratio|compliance|target|on_time|on-time|oee|utilization|score)", re.I)
    for c in columns:
        if rate_re.search(c):
            # Only promote if values are 0..1 or 0..100.
            nums = cast(
                "list[float]",
                [
                    _to_float(r.get(c))
                    for r in rows
                    if isinstance(r, dict) and _to_float(r.get(c)) is not None
                ][:50],
            )
            if nums and all(0 <= v <= 100 for v in nums) and any(v not in (0, 1, 100) for v in nums):
                roles["rate"] = c
                break

    # If no explicit value, prefer a numeric measure named revenue/cost/count.
    if roles["value"] is None:
        for c in columns:
            if re.search(r"(revenue|cost|spend|sales|amount|count|value|total|sum)", c, re.I):
                # Verify numeric.
                sample = [_to_float(r.get(c)) for r in rows if isinstance(r, dict) and _to_float(r.get(c)) is not None]
                if sample:
                    roles["value"] = c
                    break
    return roles


def _is_monotonic_decreasing(values: list[float]) -> bool:
    return all(values[i] >= values[i + 1] for i in range(len(values) - 1))


def _candidate(
    chart_type: ChartType,
    score: float,
    *,
    x_field: str | None = None,
    y_field: str | None = None,
    y2_field: str | None = None,
    chart_style: str = "",
    value_format: ValueFormat = "number",
    top_n: int | None = None,
    reason: str = "",
    supported: bool = True,
    unsupported_reason: str = "",
) -> VizCandidate:
    return VizCandidate(
        decision=VizDecision(
            chart_type=chart_type,
            chart_style=chart_style,
            x_field=x_field,
            y_field=y_field,
            y2_field=y2_field,
            value_format=value_format,
            top_n=top_n,
            reason=reason,
            confidence=round(score, 3),
        ),
        score=score,
        supported=supported,
        unsupported_reason=unsupported_reason,
    )


def recommend_visualizations(
    columns: list[str],
    rows: list[Any],
    *,
    profile: dict[str, Any] | None = None,
    intent_hint: str | None = None,
    semantic_roles: dict[str, str | None] | None = None,
    analytical_evidence: dict[str, Any] | None = None,
    method_envelope: dict[str, Any] | None = None,
    limit: int = 8,
) -> list[VizCandidate]:
    """Return a ranked list of supported visualization candidates for a result set.

    ``intent_hint`` is honoured when the shape supports it; the data always wins.
    ``semantic_roles`` and ``analytical_evidence`` allow the method engine to
    suggest richer families (radar, sankey, funnel, etc.) with explicit role
    mappings.
    ``method_envelope`` may carry analytical results (e.g. distribution groups,
    OHLC roles) that unlock richer families.
    """
    if not columns or not rows:
        return [_candidate(ChartType.TABLE, 0.2, reason="No data to plot.")]

    dict_rows = _rows_as_dicts(columns, rows)
    shape = derive_shape(columns, dict_rows, profile)
    hint = _normalize_hint(intent_hint)
    roles = semantic_roles or _detect_semantic_roles(columns, dict_rows)

    # Forced/hinted families when shape supports them.
    if hint and hint not in ("line", "area", "combo", "scatter", "kpi", "table"):
        forced = _hint_candidate(columns, dict_rows, shape, hint, roles)
        if forced:
            return [forced, *_fallback_candidates(shape, roles, exclude={hint})]

    candidates: list[VizCandidate] = []

    # 1) Single-row scalar summary -> KPI (or table if no measure).
    # A single result row with one numeric measure and no real categorical
    # dimension (or only a metric-name label dimension) is a headline metric.
    # Time columns are excluded because a lone time point is still a series
    # intent and should prefer line/area/combo.
    if shape.row_count == 1 and shape.measures and not shape.time_columns:
        non_time_label_cols = [c for c in shape.dimensions if c not in shape.time_columns]
        scalar_label = (
            len(non_time_label_cols) == 1 and _looks_like_metric_label(non_time_label_cols[0])
        )
        if not non_time_label_cols or scalar_label:
            metric = shape.measures[0]
            candidates.append(
                _candidate(
                    ChartType.KPI,
                    0.95,
                    y_field=metric,
                    value_format=detect_value_format(metric, _column_values(dict_rows, metric)),
                    reason="Single-row scalar summary — headline metric as a KPI tile.",
                )
            )
            candidates.append(
                _candidate(
                    ChartType.GAUGE,
                    0.85,
                    y_field=metric,
                    value_format=detect_value_format(metric, _column_values(dict_rows, metric)),
                    reason="Single scalar value shown as a radial gauge.",
                )
            )
            candidates.append(_candidate(ChartType.TABLE, 0.1, reason="Single row — table fallback."))
            return sorted(candidates, key=lambda c: c.score, reverse=True)

    if shape.row_count == 1 and not shape.measures:
        return [_candidate(ChartType.TABLE, 0.1, reason="Single row with no numeric metric.")]

    # No measures at all -> table.
    if not shape.measures:
        return [_candidate(ChartType.TABLE, 0.9, reason="No numeric measure to plot — showing detail rows.")]

    label_col = _primary_dimension(shape)
    value_col = shape.measures[0]
    values = _column_values(dict_rows, value_col, limit=200)
    vfmt = detect_value_format(value_col, values)
    label_card = _dimension_cardinality(shape, label_col)
    all_positive = all((f := _to_float(v)) is None or f >= 0 for v in values)
    labels = [str(v) for v in _column_values(dict_rows, label_col, limit=50)] if label_col else []
    label_is_period = label_col is not None and _is_period_dimension(shape, label_col)

    # 2) Sankey: explicit source/target/value roles.
    source_col = roles.get("source")
    target_col = roles.get("target")
    value_col_for_flow = roles.get("value")
    if source_col and target_col and value_col_for_flow:
        candidates.append(
            _candidate(
                ChartType.SANKEY,
                0.92,
                x_field=source_col,
                y_field=target_col,
                value_format=detect_value_format(value_col_for_flow, _column_values(dict_rows, value_col_for_flow, 50)),
                reason=f"Source→target flow: {source_col} → {target_col} weighted by {value_col_for_flow}.",
            )
        )

    # 3) Time series -> line / area / combo.
    is_time = bool(shape.time_columns) or (label_col is not None and _is_period_dimension(shape, label_col))
    time_col = shape.time_columns[0] if shape.time_columns else label_col
    if is_time and time_col:
        if len(shape.measures) >= 2:
            candidates.append(
                _candidate(
                    ChartType.COMBO,
                    0.92,
                    x_field=time_col,
                    y_field=shape.measures[0],
                    y2_field=shape.measures[1],
                    value_format=vfmt,
                    reason="Two metrics over a shared time axis — combo (bar + line).",
                )
            )
            candidates.append(
                _candidate(
                    ChartType.LINE,
                    0.75,
                    x_field=time_col,
                    y_field=value_col,
                    value_format=vfmt,
                    reason="Ordered time-period labels — trend over time.",
                )
            )
            candidates.append(
                _candidate(
                    ChartType.AREA,
                    0.6,
                    x_field=time_col,
                    y_field=value_col,
                    value_format=vfmt,
                    reason="Cumulative or volume trend over time.",
                )
            )
        else:
            candidates.append(
                _candidate(
                    ChartType.LINE,
                    0.92,
                    x_field=time_col,
                    y_field=value_col,
                    value_format=vfmt,
                    reason="Ordered time-period labels — trend over time.",
                )
            )
            candidates.append(
                _candidate(
                    ChartType.AREA,
                    0.68,
                    x_field=time_col,
                    y_field=value_col,
                    value_format=vfmt,
                    reason="Cumulative or volume trend over time.",
                )
            )

    # Gauge is only appropriate for a single-row scalar summary; it is handled
    # in branch (1). Multi-point time series should never collapse to a gauge.

    # 3a) Time-series bar: a period axis is valid as a simple bar chart, but
    # it is *not* a category ranking and must not use top-N capping.
    if is_time and label_col is not None:
        candidates.append(
            _candidate(
                ChartType.BAR,
                0.45,
                x_field=label_col,
                y_field=value_col,
                value_format=vfmt,
                reason="Time-series values shown as bars for each period.",
            )
        )

    # 4) Two numeric measures -> scatter / effect scatter.
    # A categorical label is fine as a point name, but a period axis should prefer
    # the time-series families above.
    if len(shape.measures) >= 2 and not is_time:
        candidates.append(
            _candidate(
                ChartType.SCATTER,
                0.88,
                x_field=shape.measures[0],
                y_field=shape.measures[1],
                value_format=vfmt,
                reason="Two numeric measures with no category — correlation scatter.",
            )
        )
        candidates.append(
            _candidate(
                ChartType.EFFECT_SCATTER,
                0.6,
                x_field=shape.measures[0],
                y_field=shape.measures[1],
                value_format=vfmt,
                reason="Emphasize individual observations with ripple effects.",
            )
        )

    # 4b) Heatmap: two categorical dimensions and a numeric measure.
    if len(shape.dimensions) >= 2 and len(shape.measures) >= 1:
        non_period_dims = [c for c in shape.dimensions if not _is_period_dimension(shape, c)]
        dims = non_period_dims if len(non_period_dims) >= 2 else shape.dimensions[:2]
        if len(dims) >= 2:
            x_dim, y_dim = dims[0], dims[1]
            measure = shape.measures[0]
            candidates.append(
                _candidate(
                    ChartType.HEATMAP,
                    0.74,
                    x_field=x_dim,
                    y_field=measure,
                    y2_field=y_dim,
                    value_format=detect_value_format(measure, _column_values(dict_rows, measure, 50)),
                    reason=f"Two dimensions ({x_dim}, {y_dim}) and a measure ({measure}) — heatmap.",
                )
            )

    # 5) Funnel: stage-like labels and monotonically decreasing values.
    stage_col = roles.get("stage")
    if stage_col and label_col == stage_col and all_positive:
        stage_values = [
            v
            for v in [_to_float(r.get(stage_col)) for r in dict_rows if isinstance(r, dict)]
            if v is not None
        ]
        if stage_values and _is_monotonic_decreasing(stage_values):
            candidates.append(
                _candidate(
                    ChartType.FUNNEL,
                    0.85,
                    x_field=stage_col,
                    y_field=value_col,
                    value_format=vfmt,
                    reason="Stage progression with decreasing values — funnel.",
                )
            )

    # 6) Radar / radial bar / treemap / funnel / pie / bar for genuine category axes only.
    # A period/time axis must not masquerade as categories (e.g. 24 months becoming
    # "24 categories" in a ranked horizontal bar, or a rate metric triggering
    # radial_bar "by category"). Time-series shapes are handled above.
    if label_col is not None and not label_is_period:
        # Radar: 3-8 numeric measures per entity, or pivoted scorecard.
        if len(shape.measures) >= 3 and 1 <= label_card <= 6:
            candidates.append(
                _candidate(
                    ChartType.RADAR,
                    0.65,
                    x_field=label_col,
                    y_field=value_col,
                    value_format=vfmt,
                    reason="Multiple measures compared across a few entities — radar scorecard.",
                )
            )

        # Radial bar: percentage-to-target/rate values (must be non-negative).
        rate_col = roles.get("rate")
        if rate_col:
            rate_values = _column_values(dict_rows, rate_col, 200)
            rate_positive = all((f := _to_float(v)) is None or f >= 0 for v in rate_values)
            if rate_positive:
                candidates.append(
                    _candidate(
                        ChartType.RADIAL_BAR,
                        0.7,
                        x_field=label_col,
                        y_field=rate_col,
                        value_format="percent",
                        reason="Percentage-to-target metrics by category — radial bar.",
                    )
                )

        # Treemap: hierarchical group + value.
        group_col = roles.get("group")
        if group_col and group_col != label_col and all_positive:
            candidates.append(
                _candidate(
                    ChartType.TREEMAP,
                    0.68,
                    x_field=label_col,
                    y_field=value_col,
                    value_format=vfmt,
                    reason=f"Hierarchical part-to-whole by {group_col} — treemap.",
                )
            )

        # Part-of-a-whole -> pie/donut.
        if _looks_like_share(label_col, label_card, all_positive):
            candidates.append(
                _candidate(
                    ChartType.PIE,
                    0.82,
                    chart_style="donut",
                    x_field=label_col,
                    y_field=value_col,
                    value_format=vfmt,
                    reason="A few positive categories of a whole — share breakdown.",
                )
            )

        # Categorical comparison -> bar.
        many = label_card > _HORIZONTAL_BAR_THRESHOLD or _looks_like_id_labels(labels)
        top_n = _BAR_RANK_CAP if label_card > _BAR_RANK_CAP else None
        bar_reason = (
            f"{label_card} categories — ranked top {top_n} as a horizontal bar so the axis stays readable."
            if top_n else (
                "Several categories — horizontal bar for readable labels."
                if many else "Category comparison."
            )
        )
        bar_style = "horizontal_bar" if many else ""
        candidates.append(
            _candidate(
                ChartType.BAR,
                0.78,
                chart_style=bar_style,
                x_field=label_col,
                y_field=value_col,
                value_format=vfmt,
                top_n=top_n,
                reason=bar_reason,
            )
        )

        # Additional compatible families for positive categorical data (non-time only).
        if not is_time:
            if 2 <= label_card <= 8:
                candidates.append(
                    _candidate(
                        ChartType.RADAR,
                        0.55,
                        x_field=label_col,
                        y_field=value_col,
                        value_format=vfmt,
                        reason="Multi-metric comparison of a few entities — radar scorecard.",
                    )
                )
            if all_positive and label_card >= 2:
                candidates.append(
                    _candidate(
                        ChartType.FUNNEL,
                        0.54,
                        x_field=label_col,
                        y_field=value_col,
                        value_format=vfmt,
                        reason="Stage-like or ranked categories — funnel.",
                    )
                )
                candidates.append(
                    _candidate(
                        ChartType.TREEMAP,
                        0.5,
                        x_field=label_col,
                        y_field=value_col,
                        value_format=vfmt,
                        reason="Hierarchical part-to-whole by category — treemap.",
                    )
                )
            if all_positive and 2 <= label_card <= 12:
                candidates.append(
                    _candidate(
                        ChartType.RADIAL_BAR,
                        0.52,
                        x_field=label_col,
                        y_field=value_col,
                        value_format=vfmt,
                        reason="Relative size of categories around a center — radial bar.",
                    )
                )

    # Fallback table.
    candidates.append(_candidate(ChartType.TABLE, 0.15, reason="No clear chart shape — showing detail rows."))

    # Deduplicate by chart type + style, then enforce family diversity and cap.
    seen: set[tuple[str, str]] = set()
    unique: list[VizCandidate] = []
    for c in sorted(candidates, key=lambda x: x.score, reverse=True):
        key = (c.decision.chart_type.value, c.decision.chart_style)
        if key in seen:
            continue
        seen.add(key)
        unique.append(c)

    # The markdown catalog is the hard eligibility gate: an inline branch can
    # propose a family, but only catalog-eligible families survive. This fixes
    # period/category leaks (e.g. 24 months being treated as 24 categories) and
    # keeps gated families (map) from surfacing.
    catalog_shape = _catalog_shape(shape, dict_rows, roles)
    catalog_facts = _catalog_facts(shape, dict_rows)
    # Per-dataset fit confidence (not just base eligibility) decides the order:
    # a family that is *eligible* for two dimensions may still be a poor fit when
    # a dimension is id-like (400 categories make an unreadable heatmap).
    fit_by_family = {
        rule.family: (rule, confidence)
        for rule, confidence in fit_ranked(catalog_shape, catalog_facts)
    }
    catalog_rules = {family: rule for family, (rule, _) in fit_by_family.items()}
    catalog_ok = set(catalog_rules) | {"table"}
    filtered: list[VizCandidate] = []
    for c in unique:
        family = c.decision.chart_type.value
        if family not in catalog_ok:
            continue
        entry = fit_by_family.get(family)
        if entry is not None:
            # Blend: the inline branch contributes *semantics* the catalog
            # cannot see from shape alone (part-of-whole, id-like labels, rate
            # columns); the catalog contributes *per-dataset fit* the inline
            # branch ignores (row count, cardinalities, specificity). Applying
            # the catalog's fit ratio to the inline score keeps both: a
            # semantically-right family stays on top, and any family sinks when
            # this dataset's shape makes it a poor fit.
            rule, confidence = entry
            fit_ratio = confidence / rule.score if rule.score > 0 else 0.0
            c.score = round(c.score * fit_ratio, 4)
            c.decision.confidence = c.score
        filtered.append(c)

    # Promote catalog-eligible families the inline branches never proposed, so
    # editing the markdown is enough to surface a new chart family. Families
    # that render as a parent type's variant (histogram, waterfall, bubble,
    # bump, calendar heatmap) are promoted through that parent.
    # Dedupe by family: if an inline branch already produced this ChartType it
    # picked a considered style (e.g. horizontal_bar for id-like labels), so the
    # catalog must not add a bare duplicate that outranks it.
    existing_types = {c.decision.chart_type.value for c in filtered}
    for family, rule in catalog_rules.items():
        confidence = fit_by_family[family][1]
        if confidence < 0.5:
            continue
        resolved = _catalog_chart_type(family)
        if resolved is None:
            continue
        chart_type, chart_style = resolved
        if chart_type.value in existing_types:
            continue
        existing_types.add(chart_type.value)
        filtered.append(
            _candidate(
                chart_type,
                confidence,
                chart_style=chart_style,
                reason=rule.guidance.split(".")[0] if rule.guidance else f"{family} from catalog",
            )
        )

    # When nothing fits the shape well, the detail table is the honest answer
    # rather than the least-bad chart.
    best_chart = max(
        (c.score for c in filtered if c.decision.chart_type != ChartType.TABLE),
        default=0.0,
    )
    if best_chart < _WEAK_FIT_THRESHOLD:
        for c in filtered:
            if c.decision.chart_type == ChartType.TABLE:
                c.score = max(c.score, best_chart + 0.05)
                c.decision.confidence = c.score

    return _diverse_top_n(filtered, limit)


def _hint_candidate(
    columns: list[str],
    rows: list[dict[str, Any]],
    shape: _Shape,
    hint: str,
    roles: dict[str, str | None],
) -> VizCandidate | None:
    """Build a single candidate for an explicit hint when the shape supports it."""
    if not shape.measures:
        return None
    value_col = shape.measures[0]
    label_col = _primary_dimension(shape)
    vfmt = detect_value_format(value_col, _column_values(rows, value_col, 50))
    label_card = _dimension_cardinality(shape, label_col)
    all_positive = all((f := _to_float(v)) is None or f >= 0 for v in _column_values(rows, value_col, 200))
    label_is_period = label_col is not None and _is_period_dimension(shape, label_col)

    if hint == "pie" and label_col is not None and not label_is_period and all_positive and 2 <= label_card <= 8:
        return _candidate(
            ChartType.PIE,
            0.82,
            chart_style="donut",
            x_field=label_col,
            y_field=value_col,
            value_format=vfmt,
            reason="Explicit share breakdown.",
        )
    if hint == "heatmap":
        if len(shape.dimensions) >= 2 and len(shape.measures) >= 1:
            non_period = [c for c in shape.dimensions if not _is_period_dimension(shape, c)]
            dims = non_period if len(non_period) >= 2 else shape.dimensions[:2]
            if len(dims) >= 2:
                return _candidate(
                    ChartType.HEATMAP,
                    0.8,
                    x_field=dims[0],
                    y_field=shape.measures[0],
                    y2_field=dims[1],
                    value_format=detect_value_format(shape.measures[0], _column_values(rows, shape.measures[0], 50)),
                    reason="Explicit heatmap request for two dimensions and a measure.",
                )
    if hint == "radar" and label_col is not None and not label_is_period:
        return _candidate(
            ChartType.RADAR,
            0.75,
            x_field=label_col,
            y_field=value_col,
            value_format=vfmt,
            reason="Explicit radar request.",
        )
    if hint == "treemap" and label_col is not None and not label_is_period:
        return _candidate(
            ChartType.TREEMAP,
            0.75,
            x_field=label_col,
            y_field=value_col,
            value_format=vfmt,
            reason="Explicit treemap request.",
        )
    if hint == "funnel" and label_col is not None and not label_is_period:
        return _candidate(
            ChartType.FUNNEL,
            0.75,
            x_field=label_col,
            y_field=value_col,
            value_format=vfmt,
            reason="Explicit funnel request.",
        )
    if hint == "sankey":
        source_col = roles.get("source") or label_col
        target_col = roles.get("target")
        value_col_flow = roles.get("value") or value_col
        if source_col and target_col:
            return _candidate(
                ChartType.SANKEY,
                0.85,
                x_field=source_col,
                y_field=target_col,
                value_format=detect_value_format(value_col_flow, _column_values(rows, value_col_flow, 50)),
                reason="Explicit sankey request.",
            )
    if hint == "radial_bar" and label_col is not None and not label_is_period and all_positive:
        rate_col = roles.get("rate") or value_col
        rate_values = _column_values(rows, rate_col, 200)
        rate_positive = all((f := _to_float(v)) is None or f >= 0 for v in rate_values)
        if rate_positive:
            return _candidate(
                ChartType.RADIAL_BAR,
                0.75,
                x_field=label_col,
                y_field=rate_col,
                value_format="percent",
                reason="Explicit radial bar request.",
            )
    if hint == "bar" and label_col is not None:
        return _candidate(
            ChartType.BAR,
            0.78,
            x_field=label_col,
            y_field=value_col,
            value_format=vfmt,
            reason="Explicit bar request.",
        )
    if hint == "gauge" and shape.row_count == 1 and shape.measures:
        return _candidate(
            ChartType.GAUGE,
            0.78,
            y_field=value_col,
            value_format=vfmt,
            reason="Explicit gauge request — single headline value.",
        )
    if hint == "effect_scatter" and len(shape.measures) >= 2:
        return _candidate(
            ChartType.EFFECT_SCATTER,
            0.75,
            x_field=shape.measures[0],
            y_field=shape.measures[1],
            value_format=vfmt,
            reason="Explicit effect-scatter request — emphasize individual points.",
        )
    # The explicit hint cannot be honoured by this data shape; fall through to
    # the shape-driven ranking so the data always wins.
    return None


def _fallback_candidates(
    shape: _Shape,
    roles: dict[str, str | None],
    exclude: set[str],
) -> list[VizCandidate]:
    """Return the ranked candidates excluding the already-forced hint."""
    # Build a minimal columns/rows set and call the main recommender, filtering.
    if not shape.columns:
        return []
    # Rebuild a few representative rows from shape metadata is not enough, so we
    # return an empty list; the caller already has the winner it asked for.
    return []


def _diverse_top_n(candidates: list[VizCandidate], limit: int) -> list[VizCandidate]:
    """Return the top ``limit`` candidates while maximising family diversity.

    Each ``ChartType`` is treated as a family. The highest-scoring candidate from
    each family is kept first; remaining slots are filled with the next-best
    candidates. This prevents a single family (e.g. bar) from filling all six
    suggestion slots.
    """
    sorted_by_score = sorted(candidates, key=lambda c: c.score, reverse=True)
    seen_families: set[str] = set()
    first_pass: list[VizCandidate] = []
    second_pass: list[VizCandidate] = []
    for c in sorted_by_score:
        family = c.decision.chart_type.value
        if family in seen_families:
            second_pass.append(c)
        else:
            seen_families.add(family)
            first_pass.append(c)
    diverse = first_pass + second_pass
    return diverse[:limit]


def rank_visualizations(
    columns: list[str],
    rows: list[Any],
    *,
    profile: dict[str, Any] | None = None,
    intent_hint: str | None = None,
    semantic_roles: dict[str, str | None] | None = None,
    analytical_evidence: dict[str, Any] | None = None,
    method_envelope: dict[str, Any] | None = None,
    limit: int = 6,
) -> list[VizCandidate]:
    """Rank the top ``limit`` diverse, data-shape-driven chart families.

    ``intent_hint`` and ``method_envelope`` only bias scores; the data shape
    decides which families are eligible.
    """
    return recommend_visualizations(
        columns,
        rows,
        profile=profile,
        intent_hint=intent_hint,
        semantic_roles=semantic_roles,
        analytical_evidence=analytical_evidence,
        method_envelope=method_envelope,
        limit=limit,
    )


def select_visualization(
    columns: list[str],
    rows: list[Any],
    *,
    profile: dict[str, Any] | None = None,
    intent_hint: str | None = None,
) -> VizDecision:
    """Choose the best renderable chart for a result set (deterministic).

    This is the legacy single-decision entry point; it delegates to
    :func:`rank_visualizations` and returns the highest-scoring candidate.
    """
    candidates = rank_visualizations(columns, rows, profile=profile, intent_hint=intent_hint, limit=6)
    if not candidates:
        return VizDecision(ChartType.TABLE, reason="No data to plot.", confidence=1.0)
    top = candidates[0]
    return top.decision
