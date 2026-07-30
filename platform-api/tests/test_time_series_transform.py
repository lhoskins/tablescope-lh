"""Tests for the time-series percent-change transform."""

from __future__ import annotations

from app.services.time_series_transform import (
    TimeSeriesInterval,
    TimeSeriesRange,
    transform_card_time_series,
)


def _daily_series(values: list[float], start: str = "2024-01-01") -> dict:
    from datetime import date, timedelta

    start_date = date.fromisoformat(start)
    rows = [
        {"label": (start_date + timedelta(days=i)).isoformat(), "value": v}
        for i, v in enumerate(values)
    ]
    return {
        "insightId": "daily",
        "valueColumn": "Revenue",
        "chart": {
            "type": "line",
            "roles": {"x": "Period", "value": "Revenue"},
            "data": {"series": rows},
        },
    }


def _monthly_series(values: list[float], start_year: int = 2024) -> dict:
    rows = [
        {"label": f"{start_year}-{m:02d}", "value": v}
        for m, v in enumerate(values, start=1)
    ]
    return {
        "insightId": "monthly",
        "valueColumn": "GrossMarginPct",
        "chart": {
            "type": "line",
            "roles": {"x": "Period", "value": "GrossMargin"},
            "data": {"series": rows},
        },
    }


def test_percent_change_formula() -> None:
    card = _daily_series([100.0, 120.0, 90.0, 110.0])
    resp = transform_card_time_series(card, "daily", "day", "7d")
    assert len(resp.points) == 4
    assert resp.points[0].comparison_status == "missing_previous"
    assert resp.points[1].percent_change_label == "+20.0%"
    assert resp.points[2].percent_change_label == "-25.0%"
    assert resp.points[3].percent_change_label == "+22.2%"


def test_zero_baseline_omits_percent_change() -> None:
    card = _daily_series([100.0, 0.0, 110.0])
    resp = transform_card_time_series(card, "daily", "day", "7d")
    assert resp.points[2].comparison_status == "zero_baseline"
    assert resp.points[2].percent_change_ratio is None
    assert resp.points[2].percent_change_label is None


def test_negative_previous_value_computes() -> None:
    card = _daily_series([-50.0, -40.0])
    resp = transform_card_time_series(card, "daily", "day", "7d")
    assert resp.points[1].comparison_status == "valid"
    # (-40 - -50) / -50 == -0.20 -> -20.0%
    assert resp.points[1].percent_change_label == "-20.0%"


def test_missing_period_not_treated_as_zero() -> None:
    # Jan and Mar are present; Feb is missing. Mar's previous period (Feb) is
    # absent, so the comparison is marked missing_previous rather than treating
    # the gap as zero.
    card = {
        "insightId": "monthly",
        "valueColumn": "GrossMarginPct",
        "chart": {
            "type": "line",
            "roles": {"x": "Period", "value": "GrossMargin"},
            "data": {
                "series": [
                    {"label": "2024-01", "value": 100.0},
                    {"label": "2024-03", "value": 130.0},
                ]
            },
        },
    }
    resp = transform_card_time_series(card, "monthly", "month", "90d")
    labels = [p.label for p in resp.points]
    assert labels == ["2024-01", "2024-03"]
    assert resp.points[0].comparison_status == "missing_previous"
    assert resp.points[1].comparison_status == "missing_previous"


def test_partial_period_suppressed_for_ratio_metric() -> None:
    from datetime import date

    # Three monthly values; fix as_of to mid-March so the March bucket is partial.
    card = _monthly_series([0.30, 0.31, 0.32])
    resp = transform_card_time_series(
        card, "monthly", "month", "90d", as_of=date(2024, 3, 15)
    )
    partial = resp.points[-1]
    assert partial.label == "2024-03"
    assert partial.partial is True
    assert partial.comparison_status == "partial_period"
    assert partial.percent_change_ratio is None
    assert "partial" in partial.warnings[0].lower()


def test_unsupported_interval_rejects_gracefully() -> None:
    # Yearly source, request day: day is finer than source grain.
    card = _monthly_series([100.0], start_year=2024)
    card["chart"]["data"]["series"] = [{"label": "2024", "value": 100.0}]
    resp = transform_card_time_series(card, "yearly", "day", "7d")
    assert resp.eligible is False
    assert resp.supported_intervals == ["year"]


def test_week_bucket_aggregation_sums_daily_values() -> None:
    # 10 days spanning two ISO weeks; sum within each week.
    card = _daily_series([10.0] * 10, start="2024-01-01")
    resp = transform_card_time_series(card, "daily", "week", "30d")
    labels = [p.label for p in resp.points]
    assert all("-W" in label for label in labels)
    # Week 1 has Mon-Sun (2024-01-01 to 2024-01-07): 7 points, sum=70.
    assert resp.points[0].current_value == 70.0


def test_range_window_includes_hidden_baseline_period() -> None:
    # 30D range ending on 2024-03-31 (source period end). Only March overlaps
    # the window, but February is kept as the hidden baseline for the
    # period-over-period comparison.
    card = _monthly_series([100.0, 110.0, 130.0])
    resp = transform_card_time_series(card, "monthly", "month", "30d")
    assert [p.label for p in resp.points] == ["2024-03"]
    assert resp.points[0].previous_value == 110.0
    assert resp.points[0].percent_change_label == "+18.2%"
    assert resp.calculation.previous_periods_included == 1


def test_gross_margin_monthly_example() -> None:
    card = {
        "insightId": "gm",
        "valueColumn": "GrossMargin",
        "chart": {
            "type": "line",
            "roles": {"x": "Period", "value": "GrossMargin"},
            "data": {
                "series": [
                    {"label": "2024-01", "value": 30.9},
                    {"label": "2024-02", "value": 25.2},
                    {"label": "2024-03", "value": 30.7},
                    {"label": "2024-04", "value": 30.4},
                    {"label": "2024-05", "value": 26.3},
                    {"label": "2024-06", "value": 24.7},
                    {"label": "2024-07", "value": 27.9},
                    {"label": "2024-08", "value": 30.0},
                    {"label": "2024-09", "value": 26.5},
                    {"label": "2024-10", "value": 30.7},
                    {"label": "2024-11", "value": 30.3},
                    {"label": "2024-12", "value": 24.4},
                ]
            },
        },
    }
    resp = transform_card_time_series(card, "gm", "month", "1y")
    assert resp.metric.is_rate_or_ratio is True
    assert resp.points[0].comparison_status == "missing_previous"
    assert resp.points[1].percent_change_label == "-18.4%"
    assert resp.points[-1].percent_change_label == "-19.5%"
    # Dec is the most recent complete period, not partial, because as_of is
    # derived from the end of the latest source period.
    assert not resp.points[-1].partial


def test_response_metadata_fields() -> None:
    card = _daily_series([100.0, 110.0])
    resp = transform_card_time_series(card, "daily", "day", "7d")
    assert resp.insight_id == "daily"
    assert resp.interval == TimeSeriesInterval.DAY
    assert resp.range == TimeSeriesRange.DAYS_7
    assert resp.timezone == "UTC"
    assert resp.calculation.formula == "((current_value - previous_value) / previous_value) * 100"
    assert resp.comparison_label == "Compared with the previous day"
