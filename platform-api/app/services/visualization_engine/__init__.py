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
from .catalog import (
    _HINT_ALIASES,
    _WEAK_FIT_THRESHOLD,
    _catalog_chart_type,
    _catalog_facts,
    _catalog_shape,
    _normalize_hint,
    normalize_chart_hint,
)
from .heuristics import (
    _COUNT_COL_RE,
    _CURRENCY_COL_RE,
    _ID_COLUMN_NAME_RE,
    _ID_LABEL_RE,
    _IDENTIFIER_MIN_ROWS,
    _IDENTIFIER_UNIQUENESS,
    _METRIC_LABEL_KEYS,
    _PCT_COL_RE,
    _SHARE_LABEL_KEYS,
    _detect_semantic_roles,
    _is_monotonic_decreasing,
    _looks_like_id_labels,
    _looks_like_metric_label,
    _looks_like_share,
    business_dimensions,
    detect_value_format,
    is_identifier_column,
)
from .recommend import (
    _candidate,
    _categorical_bar,
    _diverse_top_n,
    _fallback_candidates,
    _hint_candidate,
    rank_visualizations,
    recommend_visualizations,
    select_visualization,
)
from .shape import (
    _BAR_RANK_CAP,
    _HORIZONTAL_BAR_THRESHOLD,
    _PERIOD_COL_RE,
    _PERIOD_LABEL_RE,
    _cardinality,
    _classify_column,
    _column_values,
    _dimension_cardinality,
    _has_negative,
    _has_ohlc_roles,
    _is_period_dimension,
    _looks_hierarchical,
    _primary_dimension,
    _rows_as_dicts,
    _to_float,
    derive_shape,
)
from .types import CHART_TYPES, ChartType, ValueFormat, VizCandidate, VizDecision, _ColumnShape, _Shape

Shape = _Shape

__all__ = [
    "CHART_TYPES",
    "ChartType",
    "Shape",
    "ValueFormat",
    "VizCandidate",
    "VizDecision",
    "_ColumnShape",
    "_Shape",
    "_HINT_ALIASES",
    "_WEAK_FIT_THRESHOLD",
    "_catalog_chart_type",
    "_catalog_facts",
    "_catalog_shape",
    "_normalize_hint",
    "normalize_chart_hint",
    "_COUNT_COL_RE",
    "_CURRENCY_COL_RE",
    "_ID_COLUMN_NAME_RE",
    "_ID_LABEL_RE",
    "_IDENTIFIER_MIN_ROWS",
    "_IDENTIFIER_UNIQUENESS",
    "_METRIC_LABEL_KEYS",
    "_PCT_COL_RE",
    "_SHARE_LABEL_KEYS",
    "_detect_semantic_roles",
    "_is_monotonic_decreasing",
    "_looks_like_id_labels",
    "_looks_like_metric_label",
    "_looks_like_share",
    "business_dimensions",
    "detect_value_format",
    "is_identifier_column",
    "_candidate",
    "_categorical_bar",
    "_diverse_top_n",
    "_fallback_candidates",
    "_hint_candidate",
    "rank_visualizations",
    "recommend_visualizations",
    "select_visualization",
    "_BAR_RANK_CAP",
    "_HORIZONTAL_BAR_THRESHOLD",
    "_PERIOD_COL_RE",
    "_PERIOD_LABEL_RE",
    "_cardinality",
    "_classify_column",
    "_column_values",
    "_dimension_cardinality",
    "_has_negative",
    "_has_ohlc_roles",
    "_is_period_dimension",
    "_looks_hierarchical",
    "_primary_dimension",
    "_rows_as_dicts",
    "_to_float",
    "derive_shape",
]
