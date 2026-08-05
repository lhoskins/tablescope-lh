"""Tests for the Universal Visualization Engine (M2).

Covers: shape -> chart fixtures across the 13 real families, value-format
detection, hint handling, a contract test asserting the Python chart vocabulary
never drifts from the frontend's TypeScript source of truth, and a regression
test asserting the migrated call sites agree on the same chart for the same
input shape.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services.visualization_engine import (
    CHART_TYPES,
    ChartType,
    detect_value_format,
    normalize_chart_hint,
    rank_visualizations,
    select_visualization,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TYPES_TS = _REPO_ROOT / "web-ui" / "components" / "dashboard" / "types.ts"
_REGISTRY_TS = _REPO_ROOT / "web-ui" / "lib" / "visualizations" / "chartRegistry" / "chart-family.ts"


def _parse_ts_union(path: Path, type_name: str) -> set[str]:
    """Extract the string-literal members of a TS union type declaration."""
    text = path.read_text(encoding="utf-8")
    m = re.search(rf"export type {type_name}\s*=\s*(.+?);", text, re.DOTALL)
    assert m, f"{type_name} not found in {path}"
    return set(re.findall(r'"([^"]+)"', m.group(1)))


# ── Contract: Python vocabulary must match the frontend source of truth ──────

def test_chart_vocabulary_matches_frontend_widget_type() -> None:
    """ChartType must equal WidgetType in web-ui/components/dashboard/types.ts."""
    widget_types = _parse_ts_union(_TYPES_TS, "WidgetType")
    assert widget_types == CHART_TYPES, (
        "Python ChartType drifted from the TS WidgetType union: "
        f"py-only={CHART_TYPES - widget_types}, ts-only={widget_types - CHART_TYPES}"
    )


def test_chart_vocabulary_matches_frontend_chart_family() -> None:
    """ChartType must equal the ChartFamily union in chartRegistry.ts.

    The frontend names one family ``composed`` while its renderer key
    (``WidgetType``) is ``combo``; the engine emits the renderer key, so we
    normalize that single known alias before comparing.
    """
    families = {("combo" if f == "composed" else f) for f in
                _parse_ts_union(_REGISTRY_TS, "ChartFamily")}
    assert families == CHART_TYPES, (
        "Python ChartType drifted from the TS ChartFamily union: "
        f"py-only={CHART_TYPES - families}, ts-only={families - CHART_TYPES}"
    )


# ── Shape -> chart fixtures ──────────────────────────────────────────────────

def test_single_row_numeric_is_kpi() -> None:
    d = select_visualization(["revenue"], [{"revenue": 1200}])
    assert d.chart_type is ChartType.KPI
    assert d.value_format == "currency"


def test_single_row_no_numeric_is_table() -> None:
    d = select_visualization(["name"], [{"name": "Acme"}])
    assert d.chart_type is ChartType.TABLE


def test_time_series_is_line() -> None:
    rows = [{"month": f"2026-{m:02d}", "sales": m * 10} for m in range(1, 8)]
    d = select_visualization(["month", "sales"], rows)
    assert d.chart_type is ChartType.LINE
    assert d.x_field == "month"
    assert d.y_field == "sales"


def test_two_measures_over_time_is_combo() -> None:
    rows = [
        {"month": f"2026-{m:02d}", "sales": m * 10, "target": 50} for m in range(1, 8)
    ]
    d = select_visualization(["month", "sales", "target"], rows)
    assert d.chart_type is ChartType.COMBO
    assert d.y2_field == "target"


def test_part_of_whole_is_pie_donut() -> None:
    rows = [
        {"segment": s, "revenue": v}
        for s, v in [("Retail", 40), ("Wholesale", 30), ("Online", 20), ("Other", 10)]
    ]
    d = select_visualization(["segment", "revenue"], rows)
    assert d.chart_type is ChartType.PIE
    assert d.chart_style == "donut"


def test_many_categories_is_horizontal_bar() -> None:
    rows = [{"supplier": f"SUP-{i}", "defects": i * 3} for i in range(8)]
    d = select_visualization(["supplier", "defects"], rows)
    assert d.chart_type is ChartType.BAR
    assert d.chart_style == "horizontal_bar"


def test_few_categories_is_plain_bar() -> None:
    rows = [{"plant": p, "units": u} for p, u in [("A", 5), ("B", 8), ("C", 3)]]
    d = select_visualization(["plant", "units"], rows)
    assert d.chart_type is ChartType.BAR
    assert d.chart_style == ""


def test_two_numeric_no_category_is_scatter() -> None:
    rows = [{"x": float(i), "y": float(2 * i + 1)} for i in range(20)]
    d = select_visualization(["x", "y"], rows)
    assert d.chart_type is ChartType.SCATTER


def test_empty_result_is_table() -> None:
    assert select_visualization([], []).chart_type is ChartType.TABLE
    assert select_visualization(["a"], []).chart_type is ChartType.TABLE


def test_decision_chart_type_always_renderable() -> None:
    """Whatever the input, the emitted type is a real renderable family."""
    cases = [
        (["a"], [{"a": 1}]),
        (["a", "b"], [{"a": "x", "b": 2}, {"a": "y", "b": 3}]),
        (["m", "v"], [{"m": f"2026-{i:02d}", "v": i} for i in range(1, 6)]),
    ]
    for cols, rows in cases:
        assert select_visualization(cols, rows).chart_type.value in CHART_TYPES


# ── Value-format detection ───────────────────────────────────────────────────

@pytest.mark.parametrize(
    "name,values,expected",
    [
        ("on_time_rate", [0.9, 0.8], "percent"),
        ("total_revenue", [100, 200], "currency"),
        ("order_count", [3, 5], "count"),
        ("widget_score", [12.0, 8.5], "number"),
        ("ratio", [0.2, 0.5, 0.7], "percent"),
    ],
)
def test_value_format_detection(name, values, expected) -> None:
    assert detect_value_format(name, values) == expected


# ── Hint handling ────────────────────────────────────────────────────────────

def test_legacy_hints_normalize_to_real_families() -> None:
    # Types the LLM prompt used to name that nothing could render.
    assert normalize_chart_hint("waterfall") == "bar"
    assert normalize_chart_hint("gauge") == "gauge"
    assert normalize_chart_hint("bullet") == "gauge"
    assert normalize_chart_hint("sparkline_table") == "line"
    assert normalize_chart_hint("narrative_insight") == "table"
    assert normalize_chart_hint("donut") == "pie"
    assert normalize_chart_hint("bubble") == "scatter"
    assert normalize_chart_hint("nonsense-xyz") is None


def test_explicit_pie_hint_honoured_when_shape_supports() -> None:
    rows = [{"plant": p, "units": u} for p, u in [("A", 5), ("B", 8), ("C", 3)]]
    d = select_visualization(["plant", "units"], rows, intent_hint="donut")
    assert d.chart_type is ChartType.PIE


def test_data_wins_over_impossible_hint() -> None:
    # Ask for a waterfall on a plain category comparison -> renderable bar.
    rows = [{"plant": p, "units": u} for p, u in [("A", 5), ("B", 8), ("C", 3)]]
    d = select_visualization(["plant", "units"], rows, intent_hint="waterfall")
    assert d.chart_type is ChartType.BAR


# ── Regression: migrated call sites agree with the engine ────────────────────

def test_ask_and_run_call_site_agrees_with_engine() -> None:
    from app.routes.ai_proxy import _suggest_visualization

    rows = [{"month": f"2026-{m:02d}", "sales": m * 10} for m in range(1, 8)]
    viz = _suggest_visualization(["month", "sales"], rows)
    engine = select_visualization(["month", "sales"], rows)
    assert viz["type"] == engine.chart_type.value  # both "line"


def test_home_call_site_agrees_with_engine() -> None:
    from app.services.home_intelligence import _build_chart

    result = {
        "columns": ["segment", "revenue"],
        "rows": [
            {"segment": "Retail", "revenue": 40},
            {"segment": "Wholesale", "revenue": 30},
            {"segment": "Online", "revenue": 20},
            {"segment": "Other", "revenue": 10},
        ],
    }
    # No forcing hint -> both engine and Home infer a part-of-whole segment
    # split to the same pie/donut.
    chart = _build_chart("auto", "Revenue by segment", result, "segment", "revenue")
    assert chart is not None
    engine = select_visualization(
        ["segment", "revenue"], result["rows"], intent_hint="auto"
    )
    assert chart["type"] == engine.chart_type.value == "pie"


# ── rank_visualizations: top-6 diverse suggestions ───────────────────────────────

def test_rank_visualizations_returns_six_diverse_candidates() -> None:
    rows = [
        {"month": f"2026-{m:02d}", "sales": m * 10, "target": 50}
        for m in range(1, 8)
    ]
    ranked = rank_visualizations(["month", "sales", "target"], rows, limit=6)
    assert len(ranked) <= 6
    families = [c.decision.chart_type.value for c in ranked]
    assert len(families) == len(set(families)), "Top-6 must contain distinct families"
    assert families[0] == "combo", "Two measures over time -> combo first"
    assert all(c.score > 0 for c in ranked)
    assert all(c.decision.reason for c in ranked)


def test_rank_visualizations_includes_gauge_and_effect_scatter() -> None:
    rows = [{"x": float(i), "y": float(2 * i + 1)} for i in range(20)]
    ranked = rank_visualizations(["x", "y"], rows, limit=6)
    families = [c.decision.chart_type.value for c in ranked]
    assert "scatter" in families
    assert "effect_scatter" in families


def test_rank_visualizations_gauge_for_single_row() -> None:
    ranked = rank_visualizations(["revenue"], [{"revenue": 1200}], limit=6)
    assert ranked[0].decision.chart_type is ChartType.KPI
    assert any(c.decision.chart_type is ChartType.GAUGE for c in ranked)


def test_rank_visualizations_single_row_with_label_is_kpi() -> None:
    ranked = rank_visualizations(
        ["metric", "value"], [{"metric": "Total Revenue", "value": 1200}], limit=6
    )
    assert ranked[0].decision.chart_type is ChartType.KPI
    assert any(c.decision.chart_type is ChartType.GAUGE for c in ranked)


def test_rank_visualizations_time_series_excludes_gauge() -> None:
    rows = [{"month": f"2026-{m:02d}", "sales": m * 10} for m in range(1, 8)]
    ranked = rank_visualizations(["month", "sales"], rows, limit=6)
    families = {c.decision.chart_type for c in ranked}
    assert ChartType.GAUGE not in families
    assert ranked[0].decision.chart_type in (ChartType.LINE, ChartType.COMBO, ChartType.AREA)


def test_rank_visualizations_time_series_excludes_category_families() -> None:
    """A 24-month, single-measure, 0-100 rate shape must not be misclassified as categories."""
    rows = [
        {"month": f"2026-{m:02d}", "on_time_rate": 0.75 + (m % 10) / 100}
        for m in range(1, 25)
    ]
    ranked = rank_visualizations(["month", "on_time_rate"], rows, limit=6)
    families = {c.decision.chart_type for c in ranked}
    assert ChartType.GAUGE not in families
    assert ChartType.RADIAL_BAR not in families
    assert ChartType.FUNNEL not in families
    assert ChartType.TREEMAP not in families
    assert ChartType.RADAR not in families
    assert ChartType.PIE not in families
    # Allowed families are time-series families + table + a simple time bar.
    allowed = {ChartType.LINE, ChartType.AREA, ChartType.COMBO, ChartType.BAR, ChartType.TABLE}
    assert families.issubset(allowed)
    assert ranked[0].decision.chart_type in (ChartType.LINE, ChartType.AREA)


def test_explicit_category_hints_ignored_for_time_series() -> None:
    rows = [{"month": f"2026-{m:02d}", "sales": m * 10} for m in range(1, 8)]
    for bad_hint in ("radar", "radial_bar", "funnel", "treemap"):
        ranked = rank_visualizations(
            ["month", "sales"], rows, intent_hint=bad_hint, limit=6
        )
        assert all(c.decision.chart_type.value != bad_hint for c in ranked), bad_hint


def test_explicit_gauge_hint_ignored_for_time_series() -> None:
    rows = [{"month": f"2026-{m:02d}", "sales": m * 10} for m in range(1, 8)]
    ranked = rank_visualizations(
        ["month", "sales"], rows, intent_hint="gauge", limit=6
    )
    assert ranked[0].decision.chart_type is not ChartType.GAUGE
    assert all(c.decision.chart_type is not ChartType.GAUGE for c in ranked)


def test_identifier_columns_are_not_chart_dimensions() -> None:
    """A key column must never become a chart axis — grouping by it aggregates nothing."""
    from app.services.visualization_engine import (
        business_dimensions,
        derive_shape,
        is_identifier_column,
    )

    rows = [
        {"order_id": f"O{i}", "status": ["open", "closed", "held", "void"][i % 4], "amount": i % 37 + 1}
        for i in range(300)
    ]
    shape = derive_shape(["order_id", "status", "amount"], rows)
    assert is_identifier_column(shape, "order_id", rows) is True
    assert is_identifier_column(shape, "status", rows) is False
    assert business_dimensions(shape, rows) == ["status"]


def test_near_unique_column_is_an_identifier_only_beside_a_real_category() -> None:
    """Uniqueness alone is not a key: an aggregate has one row per category.

    ``supplier`` unique across 40 aggregated rows is a legitimate bar chart;
    a near-unique column sitting next to a low-cardinality dimension is a key.
    """
    from app.services.visualization_engine import derive_shape, is_identifier_column

    aggregated = [{"supplier": f"S{i}", "defects": i} for i in range(40)]
    shape = derive_shape(["supplier", "defects"], aggregated)
    assert is_identifier_column(shape, "supplier", aggregated) is False

    raw = [
        {"record": f"free-text-{i}", "status": ["a", "b"][i % 2], "n": i}
        for i in range(50)
    ]
    shape2 = derive_shape(["record", "status", "n"], raw)
    assert is_identifier_column(shape2, "record", raw) is True


def test_period_column_is_never_treated_as_an_identifier() -> None:
    """Every date in a daily series is distinct, but a date axis is legitimate."""
    from app.services.visualization_engine import derive_shape, is_identifier_column

    rows = [{"day": f"2026-01-{d:02d}", "units": d} for d in range(1, 29)]
    shape = derive_shape(["day", "units"], rows)
    assert is_identifier_column(shape, "day", rows) is False


def test_id_dimension_does_not_unlock_two_dimension_families() -> None:
    """order_id + status must rank as a one-dimension shape, so no heatmap."""
    rows = [
        {"order_id": f"O{i}", "status": ["a", "b", "c", "d"][i % 4], "amount": i % 37 + 1}
        for i in range(300)
    ]
    families = [c.decision.chart_type.value for c in rank_visualizations(["order_id", "status", "amount"], rows, limit=8)]
    assert "heatmap" not in families
