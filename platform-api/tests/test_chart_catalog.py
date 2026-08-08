"""Tests for the markdown-driven chart-family catalog."""

from __future__ import annotations

from app.services.chart_catalog import (
    ShapeFacts,
    ShapeSummary,
    allowed_plan_chart_types,
    chart_families,
    eligible_families,
    fit_ranked,
    fit_score,
    load_chart_catalog,
    planner_guidance,
)

# Families the ECharts renderer resolves directly (chartRegistry.ts top-level
# keys). Kept in sync by web-ui/lib/visualizations/chartCatalogLockstep.test.ts,
# which reads the markdown and the registry together.
_RENDERER_TOP_LEVEL = {
    "kpi", "table", "line", "area", "bar", "combo", "pie", "scatter", "radar",
    "radial_bar", "treemap", "funnel", "sankey", "heatmap", "effect_scatter",
    "gauge", "sunburst", "tree", "graph", "parallel", "lines", "candlestick",
    "boxplot", "pictorial_bar", "theme_river", "map",
}
# Markdown families that render through a top-level family's subtype/alias.
_SUBTYPE_FAMILIES = {"waterfall", "bubble", "histogram", "calendar_heatmap", "bump"}


def test_catalog_parses_all_31_families():
    catalog = load_chart_catalog()
    assert len(catalog) == 31
    assert set(catalog) == _RENDERER_TOP_LEVEL | _SUBTYPE_FAMILIES


def test_every_family_has_rules_and_guidance():
    for family, rule in load_chart_catalog().items():
        assert rule.family == family
        assert rule.guidance, f"{family} has no prose guidance"
        assert 0.0 <= rule.score <= 1.0


def test_allowed_plan_chart_types_covers_families_and_subtypes():
    allowed = allowed_plan_chart_types()
    assert "line" in allowed
    assert "boxplot" in allowed
    assert "stacked_bar" in allowed  # bar subtype
    assert "donut" in allowed  # pie subtype
    assert "not_a_chart" not in allowed


def test_time_series_shape_excludes_category_and_single_value_families():
    """A monthly single-metric series must not offer gauge/radial_bar/pie/etc."""
    shape = ShapeSummary(dims=0, measures=1, traits=frozenset({"time", "period_only_dimension"}))
    families = {r.family for r in eligible_families(shape)}
    assert "line" in families
    assert "area" in families
    for wrong in ("gauge", "kpi", "radial_bar", "pie", "radar", "funnel", "treemap", "bar"):
        assert wrong not in families, f"{wrong} offered for a time series"


def test_single_scalar_shape_prefers_kpi_then_gauge():
    shape = ShapeSummary(dims=0, measures=1, traits=frozenset({"single_row"}))
    ranked = eligible_families(shape)
    families = [r.family for r in ranked]
    assert families[0] == "kpi"
    assert "gauge" in families
    assert "line" not in families  # needs time


def test_matrix_shape_offers_heatmap():
    shape = ShapeSummary(dims=2, measures=1, traits=frozenset())
    families = {r.family for r in eligible_families(shape)}
    assert "heatmap" in families
    assert "sunburst" not in families  # needs hierarchy trait


def test_distribution_shape_offers_boxplot_and_histogram():
    shape = ShapeSummary(dims=0, measures=1, traits=frozenset({"raw"}))
    families = {r.family for r in eligible_families(shape)}
    assert "boxplot" in families
    assert "histogram" in families


def test_flow_shape_offers_sankey():
    shape = ShapeSummary(dims=2, measures=1, traits=frozenset({"flow"}))
    families = {r.family for r in eligible_families(shape)}
    assert "sankey" in families
    assert "funnel" not in families  # funnel needs a single stage dimension


def test_ohlc_shape_offers_candlestick():
    shape = ShapeSummary(dims=0, measures=4, traits=frozenset({"time", "ohlc"}))
    families = {r.family for r in eligible_families(shape)}
    assert "candlestick" in families


def test_gated_map_family_never_eligible():
    shape = ShapeSummary(dims=1, measures=1, traits=frozenset({"geo"}))
    families = {r.family for r in eligible_families(shape)}
    assert "map" not in families  # score 0.00 gates it off


def test_rate_needed_for_radial_bar():
    no_rate = ShapeSummary(dims=1, measures=1, traits=frozenset())
    with_rate = ShapeSummary(dims=1, measures=1, traits=frozenset({"rate"}))
    assert "radial_bar" not in {r.family for r in eligible_families(no_rate)}
    assert "radial_bar" in {r.family for r in eligible_families(with_rate)}


def test_planner_guidance_is_full_markdown():
    text = planner_guidance()
    assert "## heatmap" in text
    assert "```rules" in text


def test_families_listing_matches_catalog():
    assert set(chart_families()) == set(load_chart_catalog())


# ── Per-dataset fit confidence ───────────────────────────────────────────────


def test_fit_demotes_heatmap_when_a_dimension_is_id_like():
    """Two dimensions make a heatmap *eligible*, but an id-like axis is a poor fit."""
    shape = ShapeSummary(dims=2, measures=1, traits=frozenset())
    good = fit_score(load_chart_catalog()["heatmap"], shape,
                     ShapeFacts(row_count=96, dim_cardinalities=(8, 12)))
    bad = fit_score(load_chart_catalog()["heatmap"], shape,
                    ShapeFacts(row_count=500, dim_cardinalities=(400, 12)))
    assert good > 0.8
    assert bad < 0.2
    assert bad < good


def test_fit_excludes_family_below_its_min_rows():
    """A boxplot needs a real distribution, not three rows."""
    shape = ShapeSummary(dims=0, measures=1, traits=frozenset({"raw"}))
    rule = load_chart_catalog()["boxplot"]
    assert fit_score(rule, shape, ShapeFacts(row_count=3)) == 0.0
    assert fit_score(rule, shape, ShapeFacts(row_count=200)) > 0.5


def test_fit_ranked_orders_true_matrix_heatmap_first():
    ranked = fit_ranked(
        ShapeSummary(dims=2, measures=1, traits=frozenset()),
        ShapeFacts(row_count=96, dim_cardinalities=(8, 12)),
    )
    assert ranked[0][0].family == "heatmap"


def test_fit_ranked_scores_are_bounded_and_sorted():
    ranked = fit_ranked(
        ShapeSummary(dims=2, measures=1, traits=frozenset({"flow"})),
        ShapeFacts(row_count=40, dim_cardinalities=(6, 8)),
    )
    scores = [s for _, s in ranked]
    assert scores == sorted(scores, reverse=True)
    assert all(0.0 < s <= 1.0 for s in scores)


def test_specificity_prefers_family_using_all_dimensions():
    """A 2-dimension dataset is better explained by a family that uses both."""
    shape = ShapeSummary(dims=2, measures=1, traits=frozenset())
    facts = ShapeFacts(row_count=96, dim_cardinalities=(8, 12))
    cat = load_chart_catalog()
    assert fit_score(cat["heatmap"], shape, facts) > fit_score(cat["bar"], shape, facts)
