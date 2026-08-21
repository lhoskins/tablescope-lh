"""Unit tests for the ServiceNow ITSM metric engine."""

from __future__ import annotations

import datetime
import math

from app.services.itsm_metrics.comparison import compute_comparison, outcome_color_class
from app.services.itsm_metrics.engine import (
    _build_combined_metric_sql,
    _build_metric_sql,
    _extract_metric_value,
    _fetch_period_rows,
    _format_filter,
    _month_bounds,
    _period_epoch,
    _reporting_bounds,
    _rolling_month_bounds,
)
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

    def test_rolling_window_contains_twelve_complete_months(self) -> None:
        current, _ = _month_bounds(datetime.datetime(2026, 8, 14, tzinfo=datetime.UTC))
        rolling = _rolling_month_bounds(current)
        assert rolling.start == "2025-08-01"
        assert rolling.end == "2026-07-31"

    def test_reporting_windows_compare_equal_30_day_periods(self) -> None:
        current, previous = _reporting_bounds(
            "30_days",
            datetime.datetime(2026, 8, 14, tzinfo=datetime.UTC),
        )
        assert (current.start, current.end) == ("2026-07-02", "2026-07-31")
        assert (previous.start, previous.end) == ("2026-06-02", "2026-07-01")

    def test_reporting_windows_compare_equal_years(self) -> None:
        current, previous = _reporting_bounds(
            "1_year",
            datetime.datetime(2026, 8, 14, tzinfo=datetime.UTC),
        )
        assert (current.start, current.end) == ("2025-08-01", "2026-07-31")
        assert (previous.start, previous.end) == ("2024-08-01", "2025-07-31")


class TestFilterFormatting:
    def test_boolean_eq(self) -> None:
        from app.services.itsm_metrics.models import FilterSpec

        assert _format_filter(FilterSpec("planned", "eq", True)) == 'CAST("planned" AS boolean) = true'
        assert _format_filter(FilterSpec("planned", "eq", False)) == 'CAST("planned" AS boolean) = false'

    def test_string_eq(self) -> None:
        from app.services.itsm_metrics.models import FilterSpec

        assert _format_filter(FilterSpec("state", "eq", "Closed")) == '"state" = \'Closed\''

    def test_in_list(self) -> None:
        from app.services.itsm_metrics.models import FilterSpec

        sql = _format_filter(FilterSpec("state", "in", ["Resolved", "Closed"]))
        assert "IN ('Resolved', 'Closed')" in sql


class TestRegistry:
    def test_list_dashboards(self) -> None:
        assert list_dashboards() == [
            "availability",
            "incident",
            "incident_insights",
            "problem",
            "productivity",
            "service_request",
            "service_request_insights",
        ]

    def test_incident_metrics_have_order(self) -> None:
        metrics = get_dashboard_metrics("incident")
        assert metrics[0].order == 1
        assert all(m.dashboard == "incident" for m in metrics)

    def test_get_metric_unknown_returns_none(self) -> None:
        assert get_metric("incident", "not_a_key") is None

    def test_insight_metrics_follow_kpi_definition_directions(self) -> None:
        incident = {metric.key: metric for metric in get_dashboard_metrics("incident_insights")}
        request = {metric.key: metric for metric in get_dashboard_metrics("service_request_insights")}
        assert incident["open_backlog"].polarity == "lower_is_better"
        assert incident["resolution_sla"].polarity == "higher_is_better"
        assert incident["median_resolution"].calculation == "Median open-to-resolution duration."
        assert incident["major_incidents"].polarity == "lower_is_better"
        assert request["request_backlog"].polarity == "lower_is_better"
        assert request["request_sla"].polarity == "higher_is_better"
        assert request["median_fulfillment"].aggregation == "median"
        assert request["automated_fulfillment_rate"].polarity == "higher_is_better"


class TestSqlGeneration:
    def test_incident_volume_sql(self) -> None:
        from app.services.itsm_metrics.models import PeriodBounds

        metric = get_metric("incident", "incident_volume")
        assert metric is not None
        period = PeriodBounds(start="2026-07-01", end="2026-07-31", label="Jul 2026")
        sql = _build_metric_sql(metric, period, "US01")
        assert "01_incidents_CSV" in sql
        # sys_id is the unique record key on every ITSM CSV, so DISTINCT is
        # redundant and was dropped for query performance -- COUNT(sys_id)
        # is equivalent to COUNT(DISTINCT sys_id) here.
        assert "COUNT(sys_id)" in sql
        assert "DISTINCT" not in sql
        assert '"site_code" = \'US01\'' in sql
        assert 'unix_timestamp(CAST("opened_at" AS timestamp))' in sql

    def test_not_implemented_metric_selects_null(self) -> None:
        from app.services.itsm_metrics.models import PeriodBounds

        metric = get_metric("problem", "repeat_incident_rate")
        assert metric is not None
        period = PeriodBounds(start="2026-07-01", end="2026-07-31", label="Jul 2026")
        sql = _build_metric_sql(metric, period)
        assert "SELECT NULL AS metric_value" in sql

    def test_custom_value_expression_is_formatted(self) -> None:
        from app.services.itsm_metrics.models import PeriodBounds

        metric = get_metric("incident", "incident_rate")
        assert metric is not None
        period = PeriodBounds(start="2026-07-01", end="2026-07-31", label="Jul 2026")
        sql = _build_metric_sql(metric, period, "US01")
        assert "site_code" in sql
        assert "incident_count" in sql

    def test_median_resolution_returns_rows_for_portable_python_median(self) -> None:
        from app.services.itsm_metrics.models import PeriodBounds

        metric = get_metric("incident", "median_resolution")
        assert metric is not None
        period = PeriodBounds(start="2026-07-01", end="2026-07-31", label="Jul 2026")
        sql = _build_metric_sql(metric, period)
        assert 'CAST("resolution_minutes" AS double) AS metric_value' in sql
        assert "AVG(" not in sql
        assert _extract_metric_value([{"metric_value": 10}, {"metric_value": 30}], metric) == 20

    def test_snapshot_uses_historical_close_date_not_current_state(self) -> None:
        from app.services.itsm_metrics.models import PeriodBounds

        metric = get_metric("incident", "open_backlog")
        assert metric is not None
        period = PeriodBounds(start="2026-07-01", end="2026-07-31", label="Jul 2026")
        sql = _build_metric_sql(metric, period)
        assert '"resolved_at"' in sql
        assert '"state" IN' not in sql

    def test_automated_fulfillment_uses_available_task_proxy(self) -> None:
        from app.services.itsm_metrics.models import PeriodBounds

        metric = get_metric("service_request_insights", "automated_fulfillment_rate")
        assert metric is not None
        period = PeriodBounds(start="2026-07-01", end="2026-07-31", label="Jul 2026")
        sql = _build_metric_sql(metric, period, "US01")
        assert '"09_catalog_tasks_CSV"' in sql
        assert "task_count" in sql
        assert "automated / fulfilled" in sql
        assert '"site_code" = \'US01\'' in sql


class TestCombinedMetricSql:
    """_build_combined_metric_sql halves the number of full-CSV-scan Teiid
    queries per metric by computing current+previous in one pass instead
    of two independent queries -- see the ITSM dashboard performance
    investigation. Only mechanical, unambiguous kinds are combined; custom
    value_expression metrics (most ratio_period ones) are left untouched."""

    def _periods(self):
        from app.services.itsm_metrics.models import PeriodBounds

        return (
            PeriodBounds(start="2026-07-01", end="2026-07-31", label="Jul 2026"),
            PeriodBounds(start="2026-06-01", end="2026-06-30", label="Jun 2026"),
        )

    def test_value_expression_metrics_are_not_combined(self) -> None:
        metric = get_metric("service_request_insights", "automated_fulfillment_rate")
        assert metric is not None
        current, previous = self._periods()
        assert _build_combined_metric_sql(metric, current, previous) is None

    def test_ratio_period_metrics_are_not_combined(self) -> None:
        metric = get_metric("incident", "resolution_sla")
        assert metric is not None
        current, previous = self._periods()
        assert _build_combined_metric_sql(metric, current, previous) is None

    def test_event_period_distinct_sys_id_combines_without_distinct(self) -> None:
        metric = get_metric("incident", "major_incidents")
        assert metric is not None
        current, previous = self._periods()
        sql = _build_combined_metric_sql(metric, current, previous, "US01")
        assert sql is not None
        assert "current_value" in sql and "previous_value" in sql
        assert "DISTINCT" not in sql
        assert sql.count("COUNT(CASE WHEN") == 2
        assert '"site_code" = \'US01\'' in sql
        # The WHERE prefilter spans both periods so only one file scan happens.
        assert "01_incidents_CSV" in sql

    def test_event_period_sum_combines_with_conditional_sum(self) -> None:
        metric = get_metric("service_request", "catalog_value")
        assert metric is not None
        current, previous = self._periods()
        sql = _build_combined_metric_sql(metric, current, previous)
        assert sql is not None
        assert sql.count("SUM(CASE WHEN") == 2
        assert '"price_usd"' in sql

    def test_snapshot_eom_combines_both_period_ends_in_one_pass(self) -> None:
        metric = get_metric("incident", "open_backlog")
        assert metric is not None
        current, previous = self._periods()
        sql = _build_combined_metric_sql(metric, current, previous)
        assert sql is not None
        assert sql.count("COUNT(CASE WHEN") == 2
        assert '"resolved_at"' in sql
        # Each snapshot instant checks its own period end, not a shared one.
        assert sql.count("IS NULL OR") == 2

    def test_duration_period_average_combines_with_conditional_avg(self) -> None:
        metric = get_metric("service_request", "average_fulfillment")
        assert metric is not None
        current, previous = self._periods()
        sql = _build_combined_metric_sql(metric, current, previous)
        assert sql is not None
        assert sql.count("AVG(CASE WHEN") == 2
        assert '"request_fulfillment_minutes"' in sql

    def test_duration_period_median_returns_period_tagged_rows_not_aggregate(self) -> None:
        metric = get_metric("service_request", "median_fulfillment")
        assert metric is not None
        current, previous = self._periods()
        sql = _build_combined_metric_sql(metric, current, previous)
        assert sql is not None
        assert "AVG(" not in sql
        assert "period_tag" in sql
        assert "'current'" in sql and "'previous'" in sql


class TestFetchPeriodRows:
    """compute_metric's data-fetch step: prefer the combined single query,
    fall back to two independent queries when the metric can't be
    combined, and reshape either path back into the same
    (current_rows, previous_rows) two-list contract."""

    def _periods(self):
        from app.services.itsm_metrics.models import PeriodBounds

        return (
            PeriodBounds(start="2026-07-01", end="2026-07-31", label="Jul 2026"),
            PeriodBounds(start="2026-06-01", end="2026-06-30", label="Jun 2026"),
        )

    async def test_combinable_metric_issues_a_single_query(self, monkeypatch) -> None:
        import app.services.itsm_metrics.engine as engine

        metric = get_metric("incident", "major_incidents")
        assert metric is not None
        current, previous = self._periods()
        calls: list[str] = []

        async def fake_run_sql(database, host, port, sql):
            calls.append(sql)
            return [{"current_value": 7, "previous_value": 4}]

        monkeypatch.setattr(engine, "_run_sql", fake_run_sql)
        current_rows, previous_rows = await _fetch_period_rows(
            metric, current, previous, "US01", "seconds", "site_code", "db", "host", 5432,
        )
        assert len(calls) == 1
        assert _extract_metric_value(current_rows, metric) == 7
        assert _extract_metric_value(previous_rows, metric) == 4

    async def test_non_combinable_metric_still_issues_two_queries(self, monkeypatch) -> None:
        import app.services.itsm_metrics.engine as engine

        metric = get_metric("incident", "resolution_sla")
        assert metric is not None
        current, previous = self._periods()
        calls: list[str] = []

        async def fake_run_sql(database, host, port, sql):
            calls.append(sql)
            return [{"metric_value": 91.2}]

        monkeypatch.setattr(engine, "_run_sql", fake_run_sql)
        current_rows, previous_rows = await _fetch_period_rows(
            metric, current, previous, None, "seconds", "site_code", "db", "host", 5432,
        )
        assert len(calls) == 2
        assert _extract_metric_value(current_rows, metric) == 91.2
        assert _extract_metric_value(previous_rows, metric) == 91.2

    async def test_median_metric_splits_combined_rows_by_period_tag(self, monkeypatch) -> None:
        import app.services.itsm_metrics.engine as engine

        metric = get_metric("service_request", "median_fulfillment")
        assert metric is not None
        current, previous = self._periods()

        async def fake_run_sql(database, host, port, sql):
            return [
                {"metric_value": 10, "period_tag": "current"},
                {"metric_value": 30, "period_tag": "current"},
                {"metric_value": 5, "period_tag": "previous"},
                {"metric_value": 15, "period_tag": "previous"},
            ]

        monkeypatch.setattr(engine, "_run_sql", fake_run_sql)
        current_rows, previous_rows = await _fetch_period_rows(
            metric, current, previous, None, "seconds", "site_code", "db", "host", 5432,
        )
        assert _extract_metric_value(current_rows, metric) == 20
        assert _extract_metric_value(previous_rows, metric) == 10
