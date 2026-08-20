"""A query-backed dashboard widget (dataSource.kind === "query") replays its
saved SQL text verbatim against /api/query/datasource with no other hook for
the dashboard's date-range/cross-filter runtime controls -- selecting a
different period silently did nothing. _apply_global_filters closes that gap
by wrapping the SQL as a filtered derived table.

Run from ``platform-api``: ``pytest -q tests/test_query_datasource_global_filters.py``.
"""

from __future__ import annotations

from app.routes.dashboards_widget_query import WidgetFilter
from app.routes.query import _apply_global_filters


def test_no_filters_returns_sql_unchanged() -> None:
    sql = 'SELECT "Month", "RevenueUSD" FROM "sales_revenue_monthly_CSV"'
    assert _apply_global_filters(sql, []) == sql


def test_date_range_filters_wrap_sql_as_a_derived_table() -> None:
    sql = 'SELECT "Month", "RevenueUSD" FROM "sales_revenue_monthly_CSV";'
    filters = [
        WidgetFilter(column="Month", operator="gte", value="2026-06-01"),
        WidgetFilter(column="Month", operator="lte", value="2026-08-31"),
    ]
    wrapped = _apply_global_filters(sql, filters)
    assert wrapped == (
        'SELECT * FROM (SELECT "Month", "RevenueUSD" FROM "sales_revenue_monthly_CSV") '
        '__filtered_base__ WHERE "Month" >= \'2026-06-01\' AND "Month" <= \'2026-08-31\''
    )


def test_trailing_semicolon_and_whitespace_are_stripped_before_wrapping() -> None:
    sql = "  SELECT 1 FROM t  ;  "
    wrapped = _apply_global_filters(sql, [WidgetFilter(column="x", operator="eq", value=1)])
    assert wrapped.startswith("SELECT * FROM (SELECT 1 FROM t) __filtered_base__")
