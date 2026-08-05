from __future__ import annotations

from typing import Any

from app.services.chart_catalog import (
    ShapeFacts,
    ShapeSummary,
)

from .heuristics import business_dimensions
from .shape import _cardinality, _has_negative, _has_ohlc_roles, _looks_hierarchical, _primary_dimension
from .types import ChartType, _Shape

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


def normalize_chart_hint(raw: str | None) -> str | None:
    """Public: map any legacy chart name to a renderable family (or ``None``)."""
    return _normalize_hint(raw)


def _normalize_hint(raw: str | None) -> str | None:
    if not raw:
        return None
    key = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
    return _HINT_ALIASES.get(key)


def _catalog_shape(
    shape: _Shape,
    dict_rows: list[dict[str, Any]],
    roles: dict[str, Any],
) -> ShapeSummary:
    """Map the engine's detailed shape to the markdown catalog's summary."""
    # Identifier columns (order_id, sku, near-unique keys) are excluded: a chart
    # grouped by a record key aggregates nothing and tells a business user
    # nothing. They must not inflate the dimension count that decides which
    # families are eligible.
    dims = business_dimensions(shape, dict_rows)
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
    dims = business_dimensions(shape, dict_rows)
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
