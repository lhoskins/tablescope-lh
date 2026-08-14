"""Unit tests for the ServiceNow ITSM metric engine."""

from __future__ import annotations

import datetime
import math

from app.services.itsm_metrics.comparison import compute_comparison, outcome_color_class
from app.services.itsm_metrics.engine import _build_metric_sql, _format_filter, _month_bounds, _period_epoch
from app.services.itsm_metrics.registry import get_dashboard_metrics, get_metric, list_dashboards


class TestComparison:
    def test_up_is_favorable_when_higher_is_better(self) -> None:
        result = compute_comparison(current_value=120, previous_value=100, polarity="higher_is_better")
        assert result["direction"] == "up"
        assert result["outcome"] == "favorable"
        assert result["delta_percent"] == 20.0
        assert "↑ 20.0%" in result["comparison_label"]

    def test_up_is_unfavorable_when_lower_is_better(self) -> None:
        result = compute_comparison(current_value=120, previous_value=100, polarity="lower_is_better")
        assert result["direction"] == "up"
        assert result["outcome"] == "unfavorable"

    def test_down_is_favorable_when_lower_is_better(self) -> None:
        result = compute_comparison(current_value=80, previous_value=100, polarity="lower_is_better")
        assert result["direction"] == "down"
        assert result["outcome"] == "favorable"
        assert result["delta_percent"] == -20.0

    def test_flat_is_neutral(self) -> None:
        result = compute_comparison(current_value=100, previous_value=100)
        assert result["direction"] == "flat"
        assert result["outcome"] == "neutral"
        assert "0.0%" in result["comparison_label"]

    def test_both_zero_is_neutral(self) -> None:
        result = compute_comparison(current_value=0, previous_value=0)
        assert result["direction"] == "flat"
        assert result["outcome"] == "neutral"

    def test_previous_zero_current_positive_is_new(self) -> None:
        result = compute_comparison(current_value=5, previous_value=0)
        assert result["direction"] == "up"
        assert result["outcome"] == "neutral"
        assert result["delta_percent"] is None
        assert result["comparison_label"] == "New vs previous"

    def test_missing_current_returns_none(self) -> None:
        result = compute_comparison(current_value=None, previous_value=100)
        assert result["direction"] is None
        assert result["outcome"] is None

    def test_missing_previous_returns_no_comparison(self) -> None:
        result = compute_comparison(current_value=100, previous_value=None)
        assert result["direction"] is None
        assert result["outcome"] == "neutral"
        assert "No prior-month comparison" in result["comparison_label"]

    def test_outcome_colors(self) -> None:
        assert outcome_color_class("favorable") == "text-emerald-600"
        assert outcome_color_class("unfavorable") == "text-rose-600"
        assert outcome_color_class("neutral") == "text-slate-500"

    def test_no_infinity_when_previous_is_zero(self) -> None:
        result = compute_comparison(current_value=100, previous_value=0)
        assert not any(
            isinstance(v, float) and (math.isinf(v) or math.isnan(v))
            for v in [result["delta_percent"], result["delta"]]
            if v is not None
        )


class TestMonthBounds:
    def test_bounds_are_full_calendar_months(self) -> None:
        as_of = datetime.datetime(2026, 7, 31, 23, 59, 59, tzinfo=datetime.UTC)
        current, previous = _month_bounds(as_of)
        assert current.start == "2026-07-01"
        assert current.end == "2026-07-31"
        assert previous.start == "2026-06-01"
        assert previous.end == "2026-06-30"

    def test_incomplete_month_rolls_back(self) -> None:
        as_of = datetime.datetime(2026, 8, 14, tzinfo=datetime.UTC)
        current, _ = _month_bounds(as_of)
        assert current.label == "Jul 2026"
        assert current.end == "2026-07-31"

    def test_epoch_conversion(self) -> None:
        from app.services.itsm_metrics.models import PeriodBounds

        period = PeriodBounds(start="2026-07-01", end="2026-07-31", label="Jul 2026")
        start, end = _period_epoch(period)
        assert start < end
        # End-of-day inclusive.
        assert end - start == 30 * 86400 + 86399


class TestFilterFormatting:
    def test_boolean_eq(self) -> None:
        from app.services.itsm_metrics.models import FilterSpec

        assert _format_filter(FilterSpec("planned", "eq", True)) == '"planned" = true'
        assert _format_filter(FilterSpec("planned", "eq", False)) == '"planned" = false'

    def test_string_eq(self) -> None:
        from app.services.itsm_metrics.models import FilterSpec

        assert _format_filter(FilterSpec("state", "eq", "Closed")) == '"state" = \'Closed\''

    def test_in_list(self) -> None:
        from app.services.itsm_metrics.models import FilterSpec

        sql = _format_filter(FilterSpec("state", "in", ["Resolved", "Closed"]))
        assert "IN ('Resolved', 'Closed')" in sql


class TestRegistry:
    def test_list_dashboards(self) -> None:
        assert list_dashboards() == ["availability", "incident", "problem", "productivity", "service_request"]

    def test_incident_metrics_have_order(self) -> None:
        metrics = get_dashboard_metrics("incident")
        assert metrics[0].order == 1
        assert all(m.dashboard == "incident" for m in metrics)

    def test_get_metric_unknown_returns_none(self) -> None:
        assert get_metric("incident", "not_a_key") is None


class TestSqlGeneration:
    def test_incident_volume_sql(self) -> None:
        from app.services.itsm_metrics.models import PeriodBounds

        metric = get_metric("incident", "incident_volume")
        assert metric is not None
        period = PeriodBounds(start="2026-07-01", end="2026-07-31", label="Jul 2026")
        sql = _build_metric_sql(metric, period, "US01")
        assert "01_incidents_CSV" in sql
        assert "COUNT(DISTINCT sys_id)" in sql
        assert '"site_code" = \'US01\'' in sql
        assert "CAST(\"opened_at\" AS double)" in sql

    def test_not_implemented_metric_selects_null(self) -> None:
        from app.services.itsm_metrics.models import PeriodBounds

        metric = get_metric("problem", "repeat_incident_rate")
        assert metric is not None
        period = PeriodBounds(start="2026-07-01", end="2026-07-31", label="Jul 2026")
        sql = _build_metric_sql(metric, period)
        assert "SELECT NULL AS value" in sql

    def test_custom_value_expression_is_formatted(self) -> None:
        from app.services.itsm_metrics.models import PeriodBounds

        metric = get_metric("incident", "incident_rate")
        assert metric is not None
        period = PeriodBounds(start="2026-07-01", end="2026-07-31", label="Jul 2026")
        sql = _build_metric_sql(metric, period, "US01")
        assert "site_code" in sql
        assert "incident_count" in sql
