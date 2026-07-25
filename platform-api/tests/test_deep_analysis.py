"""Tests for method-driven Deeper analysis planning and the materiality gate."""

from __future__ import annotations

from app.services.deep_analysis import (
    DeepAnalysisSpec,
    assess_materiality,
    card_summary,
    evidence_presentation,
    plan_deep_analyses,
)


def _plan(**kwargs):
    base = dict(
        table_title="Monthly KPIs",
        period_column="month",
        measures=["revenue"],
        dimensions=[],
        row_count=24,
        period_count=24,
    )
    base.update(kwargs)
    return plan_deep_analyses(**base)


# ── Planning ─────────────────────────────────────────────────────────────────


def test_no_measures_yields_no_analyses():
    assert _plan(measures=[]) == []


def test_short_series_only_gets_period_comparison():
    """8 periods can support a period comparison but not a forecast or STL."""
    intents = {s.intent for s in _plan(period_count=8, row_count=8, max_per_table=9)}
    assert "compare_periods" in intents
    for too_hungry in ("forecast_time_series", "detect_anomalies", "trend_seasonality"):
        assert too_hungry not in intents


def test_very_short_series_yields_nothing_time_based():
    intents = {s.intent for s in _plan(period_count=3, row_count=3, max_per_table=9)}
    assert not intents & {
        "compare_periods", "detect_anomalies", "forecast_time_series", "trend_seasonality",
    }


def test_long_series_unlocks_the_deeper_time_series_methods():
    intents = {s.intent for s in _plan(period_count=36, row_count=36, max_per_table=9)}
    assert {
        "compare_periods", "detect_anomalies", "detect_change_point",
        "forecast_time_series", "trend_seasonality",
    } <= intents


def test_two_measures_unlock_relationship_analysis():
    intents = {
        s.intent
        for s in _plan(measures=["revenue", "scrap_rate"], row_count=100, max_per_table=9)
    }
    assert "relationship_numeric" in intents


def test_relationship_needs_enough_raw_rows():
    intents = {
        s.intent
        for s in _plan(measures=["revenue", "scrap_rate"], row_count=5, period_count=5, max_per_table=9)
    }
    assert "relationship_numeric" not in intents


def test_dimension_unlocks_group_comparison_and_contribution():
    specs = _plan(dimensions=["plant"], row_count=200, period_count=24, max_per_table=9)
    intents = {s.intent for s in specs}
    assert "compare_multiple_groups" in intents
    assert "contribution_to_change" in intents
    grouped = next(s for s in specs if s.intent == "compare_multiple_groups")
    assert grouped.group_by == "plant"


def test_plan_is_capped_and_ordered_by_priority():
    specs = _plan(dimensions=["plant"], measures=["revenue", "scrap"], row_count=500,
                  period_count=36, max_per_table=3)
    assert len(specs) == 3
    assert [s.priority for s in specs] == sorted((s.priority for s in specs), reverse=True)


def test_no_period_column_still_allows_cross_sectional_analyses():
    intents = {
        s.intent
        for s in plan_deep_analyses(
            table_title="Orders", period_column=None, measures=["amount", "qty"],
            dimensions=["region"], row_count=300, period_count=0, max_per_table=9,
        )
    }
    assert intents == {"relationship_numeric", "compare_multiple_groups"}


# ── Materiality gate ─────────────────────────────────────────────────────────


def _env(results, **kw):
    base = {"method": "m1", "status": "ok", "results": results, "n": 40, "usableN": 40}
    base.update(kw)
    return base


def test_missing_method_is_never_material():
    assert assess_materiality("detect_anomalies", _env({}, method=None)).material is False


def test_failed_or_unreliable_results_are_suppressed():
    assert assess_materiality("detect_trend", _env({}, status="insufficient_data")).material is False
    assert assess_materiality("detect_trend", _env({"p_value": 0.01}, quality="unreliable")).material is False


def test_anomalies_require_at_least_one_flagged_point():
    assert assess_materiality("detect_anomalies", _env({"anomalies": []})).material is False
    hit = assess_materiality("detect_anomalies", _env({"anomalies": [1, 2]}))
    assert hit.material is True
    assert "2" in hit.highlight


def test_trivial_period_change_is_suppressed():
    """A 1% move is noise; an 18% move is a story."""
    assert assess_materiality("compare_periods", _env({"relative_change": 0.01})).material is False
    big = assess_materiality("compare_periods", _env({"relative_change": 0.18}))
    assert big.material is True
    assert "18" in big.highlight


def test_period_change_reads_percentage_and_fraction_keys_unambiguously():
    """An explicit percent key is a percentage; a fraction key is a fraction."""
    # percent_change: 4.0 means +4% -> below the 5% gate.
    assert assess_materiality("compare_periods", _env({"percent_change": 4.0})).material is False
    assert assess_materiality("compare_periods", _env({"percent_change": 18.0})).material is True
    # relative_change: 1.0 means +100% (a doubling), which is very material.
    assert assess_materiality("compare_periods", _env({"relative_change": 1.0})).material is True
    # A "fraction" of 18 is implausible; treat it as 18%.
    assert assess_materiality("compare_periods", _env({"relative_change": 18.0})).material is True
    assert assess_materiality("compare_periods", _env({"relative_change": 0.02})).material is False


def test_insignificant_trend_is_suppressed():
    assert assess_materiality("detect_trend", _env({"p_value": 0.4, "slope": 2.0})).material is False
    assert assess_materiality("detect_trend", _env({"p_value": 0.01, "slope": 2.0})).material is True


def test_weak_but_significant_correlation_is_suppressed():
    """With many rows a trivial association reaches significance — still not a card."""
    weak = _env({"correlation": 0.08, "p_value": 0.001})
    assert assess_materiality("relationship_numeric", weak).material is False
    strong = _env({"correlation": 0.62, "p_value": 0.001})
    assert assess_materiality("relationship_numeric", strong).material is True


def test_group_comparison_requires_significance():
    assert assess_materiality("compare_multiple_groups", _env({"p_value": 0.3})).material is False
    assert assess_materiality("compare_multiple_groups", _env({"p_value": 0.002})).material is True


def test_change_point_and_forecast_gates():
    assert assess_materiality("detect_change_point", _env({"change_points": []})).material is False
    assert assess_materiality("detect_change_point", _env({"change_points": [4]})).material is True
    assert assess_materiality("forecast_time_series", _env({"forecast": []})).material is False
    assert assess_materiality("forecast_time_series", _env({"forecast": [1, 2, 3]})).material is True


def test_weak_seasonality_is_suppressed():
    assert assess_materiality("trend_seasonality", _env({"seasonal_strength": 0.1})).material is False
    assert assess_materiality("trend_seasonality", _env({"seasonal_strength": 0.8})).material is True


def test_unknown_intent_defaults_to_material():
    """A newly catalogued method must not be silently suppressed."""
    assert assess_materiality("some_new_intent", _env({"anything": 1})).material is True


def test_gate_never_raises_on_malformed_results():
    assert assess_materiality("relationship_numeric", _env("not-a-dict")).material is False
    assert assess_materiality("detect_anomalies", {}).material is False


# ── Presentation ─────────────────────────────────────────────────────────────


def test_evidence_presentation_maps_intents_to_layered_charts():
    assert evidence_presentation("forecast_time_series") == {
        "chart": "line", "layers": ["prediction_band"],
    }
    assert evidence_presentation("detect_anomalies")["layers"] == [
        "confidence_band", "anomaly_marker",
    ]
    assert evidence_presentation("compare_multiple_groups")["chart"] == "boxplot"
    assert evidence_presentation("relationship_numeric")["chart"] == "scatter"


def test_unknown_intent_degrades_to_table():
    assert evidence_presentation("mystery") == {"chart": "table", "layers": []}


def test_card_summary_leads_with_the_finding_then_provenance():
    spec = DeepAnalysisSpec(intent="detect_anomalies", title="t", question="q", roles={})
    mat = assess_materiality("detect_anomalies", _env({"anomalies": [1, 2, 3]}))
    summary = card_summary(spec, mat, _env({"anomalies": [1, 2, 3]}, executionEngine="r"))
    assert summary.startswith("3 observation(s) outside the expected range.")
    assert "40 observations" in summary
    assert "(R)" in summary


# ── Executive-grade analyses ─────────────────────────────────────────────────


def test_year_over_year_requires_two_calendar_years():
    """24 monthly rows inside ONE year cannot support a YoY read."""
    one_year = {s.intent for s in _plan(period_count=24, distinct_years=1, max_per_table=12)}
    assert "compare_year_over_year" not in one_year
    two_years = {s.intent for s in _plan(period_count=24, distinct_years=2, max_per_table=12)}
    assert "compare_year_over_year" in two_years


def test_year_over_year_outranks_month_over_month():
    specs = _plan(period_count=36, distinct_years=3, max_per_table=12)
    by_intent = {s.intent: s.priority for s in specs}
    assert by_intent["compare_year_over_year"] > by_intent["compare_periods"]


def test_growth_rate_and_trend_are_planned():
    intents = {s.intent for s in _plan(period_count=12, distinct_years=1, max_per_table=12)}
    assert "measure_rate_of_change" in intents
    assert "detect_trend" in intents


def test_actual_vs_target_is_planned_only_with_a_baseline_column():
    without = {s.intent for s in _plan(max_per_table=12)}
    assert "compare_to_baseline" not in without
    specs = _plan(target_column="budget_revenue", max_per_table=12)
    baseline = next(s for s in specs if s.intent == "compare_to_baseline")
    assert baseline.roles["measure2"] == "budget_revenue"
    assert baseline.presentation == "combo"


def test_two_metrics_on_a_shared_timeline_is_a_combo_not_a_scatter():
    """The co-movement read and the raw-scatter read are distinct analyses."""
    specs = _plan(measures=["revenue", "gross_margin"], row_count=200,
                  period_count=24, distinct_years=2, max_per_table=12)
    timeline = [s for s in specs if s.intent == "relationship_numeric" and s.presentation == "combo"]
    scatter = [s for s in specs if s.intent == "relationship_numeric" and s.presentation is None]
    assert len(timeline) == 1
    assert len(scatter) == 1
    assert timeline[0].roles.get("period") == "month"
    assert timeline[0].priority > scatter[0].priority


def test_driver_analysis_needs_three_measures():
    two = {s.intent for s in _plan(measures=["a", "b"], row_count=200, max_per_table=12)}
    assert "continuous_prediction" not in two
    three = {s.intent for s in _plan(measures=["a", "b", "c"], row_count=200, max_per_table=12)}
    assert "continuous_prediction" in three


def test_driver_model_with_no_explanatory_power_is_suppressed():
    weak = _env({"r_squared": 0.04, "p_value": 0.01})
    assert assess_materiality("continuous_prediction", weak).material is False
    strong = _env({"r_squared": 0.61, "p_value": 0.001})
    hit = assess_materiality("continuous_prediction", strong)
    assert hit.material is True
    assert "0.61" in hit.highlight


def test_baseline_comparison_uses_the_period_change_gate():
    assert assess_materiality("compare_to_baseline", _env({"relative_change": 0.01})).material is False
    assert assess_materiality("compare_to_baseline", _env({"relative_change": 0.22})).material is True


def test_spec_presentation_honours_the_override():
    from app.services.deep_analysis import spec_presentation

    combo = DeepAnalysisSpec(intent="relationship_numeric", title="t", question="q",
                             roles={}, presentation="combo")
    plain = DeepAnalysisSpec(intent="relationship_numeric", title="t", question="q", roles={})
    assert spec_presentation(combo)["chart"] == "combo"
    assert spec_presentation(plain)["chart"] == "scatter"
    # Layers survive the override.
    assert spec_presentation(combo)["layers"] == ["regression_line"]


def test_executive_suite_is_planned_for_a_rich_kpi_table():
    """A monthly KPI table with history, a second metric and a segment should
    offer the comparisons an executive actually asks for."""
    specs = _plan(measures=["revenue", "gross_margin", "units"], dimensions=["region"],
                  row_count=500, period_count=36, distinct_years=3,
                  target_column="budget_revenue", max_per_table=12)
    intents = {s.intent for s in specs}
    assert {
        "compare_year_over_year",
        "compare_periods",
        "compare_to_baseline",
        "measure_rate_of_change",
        "contribution_to_change",
        "detect_trend",
        "forecast_time_series",
        "continuous_prediction",
    } <= intents
