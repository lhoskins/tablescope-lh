"""ITSM metric execution engine.

Builds and executes Teiid SQL for each metric in the registry, then applies the
plan's prior-month comparison rules.
"""

from __future__ import annotations

import asyncio
import logging
import math
from calendar import monthrange
from datetime import UTC, date, datetime, timedelta, timezone
from statistics import median
from typing import Any, cast

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import SessionLocal
from app.routes.dashboards_widget_query import _run_widget_sql
from app.services.connection_pool import pool_manager
from app.services.tenant_teiid_resolver import TenantTeiidResolver

from .comparison import compute_comparison, utc_now_iso
from .models import (
    ChartResult,
    ChartSeries,
    DashboardResult,
    FilterSpec,
    InsightSummary,
    MetricDefinition,
    MetricValue,
    PeriodBounds,
)
from .registry import get_dashboard_metrics, list_dashboards

logger = logging.getLogger(__name__)

CACHE_HINT = "/*+ cache(pref_mem ttl:300000) */"

_DIMENSION_CODE_COLUMN: dict[str, str] = {
    "site": "site_code",
    "region": "region",
}

def _dimension_column(dimension: str | None) -> str:
    return _DIMENSION_CODE_COLUMN.get((dimension or "").lower(), "site_code")


_METRIC_COPY: dict[str, tuple[str, str]] = {
    "incident_volume": (
        "Incidents opened during the latest complete calendar month.",
        "Distinct incidents opened in the month.",
    ),
    "incident_rate": (
        "Monthly incident demand normalized for organization size.",
        "Distinct incidents opened ÷ employee population x 100.",
    ),
    "mean_response": (
        "Average time from incident creation to the first recorded response.",
        "Sum of first-response duration ÷ incidents with a first response.",
    ),
    "mttr": (
        "Average elapsed time to resolve incidents completed in the month.",
        "Sum of resolution duration ÷ resolved incidents.",
    ),
    "median_resolution": (
        "The midpoint resolution time, reducing the influence of extreme cases.",
        "Median resolution duration of incidents resolved in the month.",
    ),
    "mean_restore": (
        "Average duration of unplanned service outages ending in the month.",
        "Sum of unplanned outage duration ÷ unplanned outages.",
    ),
    "fcr_proxy": (
        "Resolved incidents with no reopen or reassignment activity.",
        "Resolved incidents with zero reopens and zero reassignments ÷ resolved incidents x 100.",
    ),
    "reassignment_rate": (
        "Share of incidents assigned more than once.",
        "Incidents with one or more reassignments ÷ incidents opened x 100.",
    ),
    "average_assignments": (
        "Average number of assignment touches per resolved incident.",
        "Average of initial assignment plus reassignment count.",
    ),
    "reopen_rate": (
        "Share of resolved incidents that were reopened.",
        "Resolved incidents with one or more reopens ÷ resolved incidents x 100.",
    ),
    "major_incidents": (
        "Incidents flagged as major during the month.",
        "Distinct major incidents opened in the month.",
    ),
    "major_incident_mttr": (
        "Average resolution time for major incidents.",
        "Sum of major-incident resolution duration ÷ resolved major incidents.",
    ),
    "open_backlog": (
        "Incidents still unresolved at the close of the latest complete month.",
        "Opened by month-end and unresolved or resolved after month-end.",
    ),
    "backlog_older_than_30_days": (
        "Month-end backlog opened more than 30 days earlier.",
        "Open month-end incidents with age greater than 30 days.",
    ),
    "average_open_age": (
        "Average age of unresolved incidents at month-end.",
        "Sum of open incident age at month-end ÷ open incidents.",
    ),
    "resolution_sla": (
        "Resolution SLA records completed within their target.",
        "Non-breached incident resolution SLAs ÷ completed incident resolution SLAs x 100.",
    ),
    "sla_breach_rate": (
        "Resolution SLA records that exceeded their target.",
        "Breached incident resolution SLAs ÷ completed incident resolution SLAs x 100.",
    ),
    "knowledge_reuse": (
        "Resolved incidents where a knowledge article was used.",
        "Resolved incidents with knowledge used ÷ resolved incidents x 100.",
    ),
}


def _month_bounds(as_of: datetime | None = None, tz: timezone = UTC) -> tuple[PeriodBounds, PeriodBounds]:
    """Return current and previous complete calendar month bounds."""
    now = as_of or datetime.now(tz)
    # If the current month is incomplete, the latest complete month is the previous one.
    if now.day < monthrange(now.year, now.month)[1] or now.time().hour < 23:
        current_month = date(now.year, now.month, 1) - timedelta(days=1)
    else:
        current_month = date(now.year, now.month, monthrange(now.year, now.month)[1])

    current_start = current_month.replace(day=1)
    current_end = current_month
    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end.replace(day=1)

    current = PeriodBounds(start=current_start.isoformat(), end=current_end.isoformat(), label=current_start.strftime("%b %Y"))
    previous = PeriodBounds(start=previous_start.isoformat(), end=previous_end.isoformat(), label=previous_start.strftime("%b %Y"))
    return current, previous


def _rolling_month_bounds(current: PeriodBounds, months: int = 12) -> PeriodBounds:
    """Return bounds ending with ``current`` and spanning whole calendar months."""
    current_start = date.fromisoformat(current.start)
    month_index = current_start.year * 12 + current_start.month - months
    start_year, zero_based_month = divmod(month_index, 12)
    start = date(start_year, zero_based_month + 1, 1)
    return PeriodBounds(start=start.isoformat(), end=current.end, label=f"Last {months} months")


_PERIOD_DAYS: dict[str, int] = {
    "30_days": 30,
    "60_days": 60,
    "90_days": 90,
}
_PERIOD_MONTHS: dict[str, tuple[int, str]] = {
    "6_months": (6, "6 months"),
    "1_year": (12, "1 year"),
    "2_years": (24, "2 years"),
}


def _month_window_start(end: date, months: int) -> date:
    month_index = end.year * 12 + end.month - 1 - (months - 1)
    year, zero_based_month = divmod(month_index, 12)
    return date(year, zero_based_month + 1, 1)


def _reporting_bounds(
    period_key: str | None,
    as_of: datetime | None = None,
) -> tuple[PeriodBounds, PeriodBounds]:
    """Return a complete reporting window and the preceding equal window."""
    latest_month, prior_month = _month_bounds(as_of)
    if not period_key or period_key == "latest_month":
        return latest_month, prior_month

    end = date.fromisoformat(latest_month.end)
    if period_key in _PERIOD_DAYS:
        days = _PERIOD_DAYS[period_key]
        start = end - timedelta(days=days - 1)
        previous_end = start - timedelta(days=1)
        previous_start = previous_end - timedelta(days=days - 1)
        return (
            PeriodBounds(start=start.isoformat(), end=end.isoformat(), label=f"Last {days} days"),
            PeriodBounds(
                start=previous_start.isoformat(),
                end=previous_end.isoformat(),
                label=f"prior {days} days",
            ),
        )

    if period_key in _PERIOD_MONTHS:
        months, label = _PERIOD_MONTHS[period_key]
        start = _month_window_start(end, months)
        previous_end = start - timedelta(days=1)
        previous_start = _month_window_start(previous_end, months)
        return (
            PeriodBounds(start=start.isoformat(), end=end.isoformat(), label=f"Last {label}"),
            PeriodBounds(
                start=previous_start.isoformat(),
                end=previous_end.isoformat(),
                label=f"prior {label}",
            ),
        )

    raise ValueError(f"Unsupported ITSM reporting period: {period_key}")


def _period_epoch(period: PeriodBounds) -> tuple[float, float]:
    """Convert ISO date bounds to epoch seconds."""
    start_dt = datetime.fromisoformat(period.start).replace(tzinfo=UTC)
    end_dt = datetime.fromisoformat(period.end).replace(hour=23, minute=59, second=59, tzinfo=UTC)
    return start_dt.timestamp(), end_dt.timestamp()


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _literal(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int | float):
        return str(float(value))
    return repr(str(value))


def _format_filter(f: FilterSpec) -> str:
    col = _quote_identifier(f.column)
    op = f.operator
    val = f.value
    if op == "is_null":
        return f"{col} IS NULL"
    if op == "is_not_null":
        return f"{col} IS NOT NULL"
    if op == "eq":
        if isinstance(val, bool):
            return f"CAST({col} AS boolean) = {_literal(val)}"
        return f"{col} = {_literal(val)}"
    if op == "neq":
        if isinstance(val, bool):
            return f"CAST({col} AS boolean) <> {_literal(val)}"
        return f"{col} <> {_literal(val)}"
    if op == "gt":
        return f"{col} > {_literal(val)}"
    if op == "gte":
        return f"{col} >= {_literal(val)}"
    if op == "lt":
        return f"{col} < {_literal(val)}"
    if op == "lte":
        return f"{col} <= {_literal(val)}"
    if op == "in":
        if not isinstance(val, list | tuple) or not val:
            return "1 = 0"
        values = ", ".join(_literal(v) for v in val)
        return f"{col} IN ({values})"
    if op == "not_in":
        if not isinstance(val, list | tuple) or not val:
            return "1 = 1"
        values = ", ".join(_literal(v) for v in val)
        return f"{col} NOT IN ({values})"
    return "1 = 1"


def _site_filter(site_code: str | None, site_column: str = "site_code") -> str:
    if not site_code or site_code.lower() == "all":
        return "1 = 1"
    return f"{_quote_identifier(site_column)} = {_literal(site_code)}"


def _date_expression(date_field: str | None, date_unit: str = "seconds") -> str:
    if not date_field:
        return "NULL"
    col = _quote_identifier(date_field)
    if date_unit == "seconds":
        return f"unix_timestamp(CAST({col} AS timestamp))"
    if date_unit == "milliseconds":
        return f"unix_timestamp(CAST({col} AS timestamp)) / 1000.0"
    if date_unit == "iso_string":
        return f"unix_timestamp(CAST({col} AS timestamp))"
    return f"unix_timestamp(CAST({col} AS timestamp))"


def _build_metric_sql(
    metric: MetricDefinition,
    period: PeriodBounds,
    site_code: str | None = None,
    date_unit: str = "seconds",
    site_column: str = "site_code",
) -> str:
    """Generate a value SQL query for a single metric and period."""
    if metric.status == "not_implemented":
        return "SELECT NULL AS metric_value"

    table = _quote_identifier(metric.table)
    start_epoch, end_epoch = _period_epoch(period)
    date_expr = _date_expression(metric.date_field, date_unit)

    where_clauses: list[str] = []
    for f in metric.filters:
        where_clauses.append(_format_filter(f))
    if site_code and site_code.lower() != "all":
        where_clauses.append(_site_filter(site_code, site_column))

    # Custom value expression wins.
    if metric.value_expression:
        expr = metric.value_expression.format(
            table=table,
            start=start_epoch,
            end=end_epoch,
            start_iso=repr(period.start),
            end_iso=repr(period.end),
            site_filter=_site_filter(site_code, site_column),
            date_expr=date_expr,
        )
        # If the expression already starts with SELECT, return as-is.
        if expr.strip().lower().startswith("select"):
            return f"{CACHE_HINT} {expr.lstrip()}"
        return f"{CACHE_HINT} SELECT {expr} AS metric_value"

    # Generic builders by kind.
    if metric.kind == "event_period":
        if metric.date_field:
            where_clauses.append(f"{date_expr} >= {start_epoch} AND {date_expr} <= {end_epoch}")
        target_col = _quote_identifier(metric.numerator) if metric.numerator else "sys_id"
        select = "COUNT(*)" if metric.aggregation == "count" else f"{metric.aggregation.upper()}({target_col})"
        if metric.aggregation == "distinct":
            select = "COUNT(sys_id)" if target_col == "sys_id" else f"COUNT(DISTINCT {target_col})"
        if metric.aggregation == "sum":
            select = f"SUM(CAST({target_col} AS double))"
        where = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        return f"{CACHE_HINT}\nSELECT {select} AS metric_value FROM {table} {where}"

    if metric.kind == "snapshot_eom":
        open_field = metric.date_field or "opened_at"
        close_field = getattr(metric, "close_field", "resolved_at")
        open_expr = _date_expression(open_field, date_unit)
        close_expr = _date_expression(close_field, date_unit)
        where_clauses.append(f"{open_expr} <= {end_epoch}")
        where_clauses.append(f"({close_expr} IS NULL OR {close_expr} > {end_epoch})")
        # Reconstruct the historical snapshot from opened/resolved timestamps.
        # Filtering on today's state would wrongly remove incidents that were
        # open at month-end and resolved later.
        select = "COUNT(sys_id)"
        where = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        return f"{CACHE_HINT}\nSELECT {select} AS metric_value FROM {table} {where}"

    if metric.kind == "duration_period":
        duration_col = metric.numerator or "resolution_minutes"
        where_clauses.append(f"{date_expr} >= {start_epoch} AND {date_expr} <= {end_epoch}")
        where_clauses.append(f"{_quote_identifier(duration_col)} IS NOT NULL")
        if metric.aggregation == "median":
            select = f"CAST({_quote_identifier(duration_col)} AS double)"
        else:
            select = f"AVG(CAST({_quote_identifier(duration_col)} AS double))"
        where = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        return f"{CACHE_HINT}\nSELECT {select} AS metric_value FROM {table} {where}"

    if metric.kind == "ratio_period":
        return _build_ratio_sql(metric, start_epoch, end_epoch, date_expr, where_clauses, table)

    return "SELECT NULL AS metric_value"


def _build_combined_metric_sql(
    metric: MetricDefinition,
    current_period: PeriodBounds,
    previous_period: PeriodBounds,
    site_code: str | None = None,
    date_unit: str = "seconds",
    site_column: str = "site_code",
) -> str | None:
    """Build ONE query computing both the current- and previous-period
    values for a metric, instead of two independent full-table-scan
    queries.

    Teiid's CSV-backed views cannot push a WHERE/GROUP BY/aggregate down to
    the source -- every query pays the cost of reading and parsing the
    entire source file, regardless of selectivity (see the ITSM dashboard
    performance investigation). Combining current+previous into one pass
    halves that dominant, WHERE-independent cost for the metrics this
    covers, instead of just widening the semaphore around two full scans.

    Only the safe, mechanical cases are combined: the generic kind-based
    builders (event_period, snapshot_eom, duration_period) with no custom
    ``value_expression`` and a plain count/distinct/sum aggregation.
    Metrics with a hand-written ``value_expression`` (subqueries, joins --
    most ratio_period metrics) are far too varied to rewrite generically
    and safely, so they keep running as two separate queries. Returns None
    when the metric can't be combined this way; the caller falls back to
    the existing two-query path unchanged.
    """
    if metric.value_expression or metric.status == "not_implemented":
        return None
    if metric.kind not in ("event_period", "snapshot_eom", "duration_period"):
        return None
    if not metric.date_field:
        return None

    table = _quote_identifier(metric.table)
    cur_start, cur_end = _period_epoch(current_period)
    prev_start, prev_end = _period_epoch(previous_period)
    date_expr = _date_expression(metric.date_field, date_unit)

    base_where_clauses = [_format_filter(f) for f in metric.filters]
    if site_code and site_code.lower() != "all":
        base_where_clauses.append(_site_filter(site_code, site_column))
    base_where = " AND ".join(base_where_clauses)

    if metric.kind == "event_period":
        if metric.aggregation not in ("count", "distinct", "sum"):
            return None
        target_col = _quote_identifier(metric.numerator) if metric.numerator else "sys_id"
        cur_cond = f"{date_expr} >= {cur_start} AND {date_expr} <= {cur_end}"
        prev_cond = f"{date_expr} >= {prev_start} AND {date_expr} <= {prev_end}"

        def agg(cond: str) -> str:
            if metric.aggregation == "sum":
                return f"SUM(CASE WHEN {cond} THEN CAST({target_col} AS double) END)"
            if metric.aggregation == "distinct" and target_col != "sys_id":
                return f"COUNT(DISTINCT CASE WHEN {cond} THEN {target_col} END)"
            # Plain count, or distinct on sys_id -- the unique record key on
            # every ITSM CSV, so DISTINCT is redundant here (same rationale
            # as the two-query builder's DISTINCT removal).
            counted = target_col if metric.aggregation == "distinct" else "1"
            return f"COUNT(CASE WHEN {cond} THEN {counted} END)"

        where_parts = [f"{date_expr} >= {prev_start} AND {date_expr} <= {cur_end}"]
        if base_where:
            where_parts.append(base_where)
        where = "WHERE " + " AND ".join(where_parts)
        return f"""{CACHE_HINT}
SELECT {agg(cur_cond)} AS current_value, {agg(prev_cond)} AS previous_value
FROM {table} {where}"""

    if metric.kind == "snapshot_eom":
        open_field = metric.date_field
        close_field = metric.close_field or "resolved_at"
        open_expr = _date_expression(open_field, date_unit)
        close_expr = _date_expression(close_field, date_unit)

        def snap_cond(end_epoch: float) -> str:
            return f"{open_expr} <= {end_epoch} AND ({close_expr} IS NULL OR {close_expr} > {end_epoch})"

        where_parts = [f"{open_expr} <= {cur_end}"]
        if base_where:
            where_parts.append(base_where)
        where = "WHERE " + " AND ".join(where_parts)
        return f"""{CACHE_HINT}
SELECT COUNT(CASE WHEN {snap_cond(cur_end)} THEN sys_id END) AS current_value,
       COUNT(CASE WHEN {snap_cond(prev_end)} THEN sys_id END) AS previous_value
FROM {table} {where}"""

    # duration_period
    duration_col = _quote_identifier(metric.numerator or "resolution_minutes")
    cur_cond = f"{date_expr} >= {cur_start} AND {date_expr} <= {cur_end}"
    prev_cond = f"{date_expr} >= {prev_start} AND {date_expr} <= {prev_end}"
    where_parts = [
        f"{date_expr} >= {prev_start} AND {date_expr} <= {cur_end}",
        f"{duration_col} IS NOT NULL",
    ]
    if base_where:
        where_parts.append(base_where)
    where = "WHERE " + " AND ".join(where_parts)
    if metric.aggregation == "median":
        # Median has no Teiid-portable aggregate function, so the
        # single-period path already returns raw rows and computes the
        # median in Python. Combining periods means each row must carry
        # which period it belongs to instead of a scalar aggregate.
        return f"""{CACHE_HINT}
SELECT CAST({duration_col} AS double) AS metric_value,
       CASE WHEN {cur_cond} THEN 'current' ELSE 'previous' END AS period_tag
FROM {table} {where}"""
    return f"""{CACHE_HINT}
SELECT AVG(CASE WHEN {cur_cond} THEN CAST({duration_col} AS double) END) AS current_value,
       AVG(CASE WHEN {prev_cond} THEN CAST({duration_col} AS double) END) AS previous_value
FROM {table} {where}"""


def _build_ratio_sql(
    metric: MetricDefinition,
    start_epoch: float,
    end_epoch: float,
    date_expr: str,
    where_clauses: list[str],
    table: str,
) -> str:
    if metric.numerator and metric.denominator:
        where = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        if metric.date_field:
            where = f"WHERE {date_expr} >= {start_epoch} AND {date_expr} <= {end_epoch} AND {' AND '.join(where_clauses)}"
        num_expr = _quote_identifier(metric.numerator)
        den_expr = _quote_identifier(metric.denominator)
        sql = f"""{CACHE_HINT}
SELECT CASE WHEN {den_expr} > 0 THEN CAST(100.0 * CAST({num_expr} AS double) / {den_expr} AS double) ELSE 0 END AS metric_value
FROM {table} {where}"""
        return sql
    return "SELECT NULL AS metric_value"


def _extract_single_value(rows: list[dict[str, Any]]) -> float | None:
    if not rows:
        return None
    for k in ("metric_value", "METRIC_VALUE", "value", "VALUE", "y", "Y", "count", "COUNT", "avg", "AVG"):
        if k in rows[0]:
            val = rows[0][k]
            break
    else:
        val = next(iter(rows[0].values()))
    if val is None:
        return None
    if isinstance(val, int | float):
        return float(val)
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _extract_metric_value(rows: list[dict[str, Any]], metric: MetricDefinition) -> float | None:
    if metric.aggregation != "median":
        return _extract_single_value(rows)
    values = [_extract_single_value([row]) for row in rows]
    measured = [value for value in values if value is not None]
    return float(median(measured)) if measured else None


def _convert_duration(value: float | None, source_unit: str | None, display_unit: str) -> float | None:
    if value is None:
        return None
    if source_unit == "minutes" and display_unit == "hours":
        return value / 60.0
    if source_unit == "minutes" and display_unit == "minutes":
        return value
    return value


def _display_unit(metric: MetricDefinition, duration_unit: str) -> str | None:
    if metric.unit == "minutes":
        return duration_unit
    if metric.key == "incident_rate":
        return "per 100 employees"
    return metric.unit


def _metric_description(metric: MetricDefinition) -> str:
    return metric.description or _METRIC_COPY.get(metric.key, (f"{metric.label} for the latest complete month.", ""))[0]


def _metric_calculation(metric: MetricDefinition) -> str:
    fallback = {
        "event_period": "Distinct records in the reporting period.",
        "snapshot_eom": "Records open at calendar month-end.",
        "duration_period": "Average duration for records completed in the reporting period.",
        "ratio_period": "Qualified records ÷ eligible records x 100.",
    }[metric.kind]
    return metric.calculation or _METRIC_COPY.get(metric.key, ("", fallback))[1] or fallback


def _format_value(value: float | None, metric: MetricDefinition, unit: str | None = None) -> str:
    if value is None:
        return "—"
    if math.isnan(value) or math.isinf(value):
        return "—"
    display_unit = unit or metric.unit
    if display_unit == "percent":
        return f"{value:.{metric.precision}f}%"
    if display_unit == "count":
        return f"{int(value):,}" if metric.precision == 0 else f"{value:,.{metric.precision}f}"
    if display_unit == "hours":
        return f"{value:.{metric.precision}f} hr"
    if display_unit == "minutes":
        return f"{value:.{metric.precision}f} min"
    if display_unit == "days":
        return f"{value:.{metric.precision}f} days"
    if display_unit == "per 100 employees":
        return f"{value:.{metric.precision}f} per 100"
    return f"{value:.{metric.precision}f}"


async def _resolve_teiid(
    project_id: int,
    session: AsyncSession,
    tenant_id: int,
    user_id: int,
) -> tuple[str, str, int]:
    """Resolve the Teiid database name and endpoint for a project."""
    from app.routes.dashboards_widget_query import _resolve_vdb

    database = await _resolve_vdb(
        session=session,
        context=type("Context", (), {"tenant_id": tenant_id, "user_id": user_id})(),
        project_id=project_id,
    )
    endpoint = await TenantTeiidResolver(session).resolve_for_org(tenant_id)
    return database, endpoint.pg_host, endpoint.pg_port


async def _run_sql(
    database: str,
    host: str,
    port: int,
    sql: str,
) -> list[dict[str, Any]]:
    """Execute SQL against Teiid and return rows."""
    try:
        result = await _run_widget_sql(database=database, sql=sql, teiid_host=host, teiid_port=port)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("ITSM metric query failed: %s | SQL: %s", exc, sql)
        raise HTTPException(status_code=502, detail=f"Metric query failed: {exc}") from exc
    return result["rows"]


def _metric_sql_safe(metric: MetricDefinition, period: PeriodBounds, site_code: str | None, date_unit: str, site_column: str = "site_code") -> str:
    try:
        return _build_metric_sql(metric, period, site_code, date_unit, site_column)
    except Exception as exc:
        logger.warning("SQL build failed for %s: %s", metric.key, exc)
        return "SELECT NULL AS metric_value"


async def _fetch_period_rows(
    metric: MetricDefinition,
    current_period: PeriodBounds,
    previous_period: PeriodBounds,
    site_code: str | None,
    date_unit: str,
    site_column: str,
    database: str,
    host: str,
    port: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fetch a metric's current- and previous-period rows, preferring one
    combined query over two independent full-scan queries when the metric's
    shape allows it (see _build_combined_metric_sql). Reshapes the combined
    result back into the same ``(current_rows, previous_rows)`` two-list
    shape the two-query path already produces, so downstream extraction
    (_extract_metric_value) needs no changes either way.
    """
    try:
        combined_sql = _build_combined_metric_sql(
            metric, current_period, previous_period, site_code, date_unit, site_column
        )
    except Exception as exc:
        logger.warning("Combined SQL build failed for %s: %s", metric.key, exc)
        combined_sql = None

    if combined_sql is not None:
        rows = await _run_sql(database, host, port, combined_sql)
        if metric.kind == "duration_period" and metric.aggregation == "median":
            current_rows = [
                {"metric_value": r.get("metric_value", r.get("METRIC_VALUE"))}
                for r in rows
                if r.get("period_tag", r.get("PERIOD_TAG")) == "current"
            ]
            previous_rows = [
                {"metric_value": r.get("metric_value", r.get("METRIC_VALUE"))}
                for r in rows
                if r.get("period_tag", r.get("PERIOD_TAG")) == "previous"
            ]
            return current_rows, previous_rows
        row = rows[0] if rows else {}
        current_rows = [{"metric_value": row.get("current_value", row.get("CURRENT_VALUE"))}]
        previous_rows = [{"metric_value": row.get("previous_value", row.get("PREVIOUS_VALUE"))}]
        return current_rows, previous_rows

    current_sql = _metric_sql_safe(metric, current_period, site_code, date_unit, site_column)
    previous_sql = _metric_sql_safe(metric, previous_period, site_code, date_unit, site_column)
    current_rows, previous_rows = await asyncio.gather(
        _run_sql(database, host, port, current_sql),
        _run_sql(database, host, port, previous_sql),
    )
    return current_rows, previous_rows


def _assemble_metric_value(
    metric: MetricDefinition,
    current_raw: float | None,
    previous_raw: float | None,
    current_period: PeriodBounds,
    previous_period: PeriodBounds,
    duration_unit: str,
) -> MetricValue:
    """Format a metric's already-extracted current/previous values into a KPI
    card. Shared by the per-metric Teiid path (compute_metric) and the
    in-process insight-snapshot path, so both produce identical MetricValue
    shapes regardless of where the raw numbers came from."""
    current_value = _convert_duration(current_raw, metric.unit, duration_unit)
    previous_value = _convert_duration(previous_raw, metric.unit, duration_unit)
    unit = _display_unit(metric, duration_unit)

    comparison = compute_comparison(
        current_value=current_value,
        previous_value=previous_value,
        polarity=metric.polarity,
        current_label=current_period.label,
        previous_label=previous_period.label,
        precision=metric.precision,
    )

    return MetricValue(
        metric_key=metric.key,
        label=metric.label,
        value=current_value,
        display_value=_format_value(current_value, metric, unit),
        period_start=current_period.start,
        period_end=current_period.end,
        previous_value=previous_value,
        delta=cast(float | None, comparison.get("delta")),
        delta_percent=cast(float | None, comparison.get("delta_percent")),
        direction=cast(str | None, comparison.get("direction")),
        polarity=metric.polarity,
        outcome=cast(str | None, comparison.get("outcome")),
        comparison_label=cast(str | None, comparison.get("comparison_label")),
        status=metric.status,
        as_of=utc_now_iso(),
        unit=unit,
        description=_metric_description(metric),
        calculation=_metric_calculation(metric),
        target=metric.target,
    )


async def compute_metric(
    metric: MetricDefinition,
    project_id: int,
    session: AsyncSession,
    tenant_id: int,
    user_id: int,
    current_period: PeriodBounds,
    previous_period: PeriodBounds,
    site_code: str | None = None,
    date_unit: str = "seconds",
    duration_unit: str = "hours",
    teiid_endpoint: tuple[str, str, int] | None = None,
    site_column: str = "site_code",
) -> MetricValue:
    """Run a metric for current and previous month and assemble a KPI card value."""
    if teiid_endpoint is None:
        database, host, port = await _resolve_teiid(project_id, session, tenant_id, user_id)
    else:
        database, host, port = teiid_endpoint

    current_rows, previous_rows = await _fetch_period_rows(
        metric, current_period, previous_period, site_code, date_unit, site_column, database, host, port,
    )

    return _assemble_metric_value(
        metric,
        _extract_metric_value(current_rows, metric),
        _extract_metric_value(previous_rows, metric),
        current_period,
        previous_period,
        duration_unit,
    )


def _build_chart_sql(
    metric: MetricDefinition,
    period: PeriodBounds,
    group_by: str,
    site_code: str | None,
    date_unit: str,
    site_column: str = "site_code",
) -> str:
    table = _quote_identifier(metric.table)
    start_epoch, end_epoch = _period_epoch(period)
    date_expr = _date_expression(metric.date_field, date_unit)
    group_col = _quote_identifier(group_by)
    where_clauses: list[str] = []
    for f in metric.filters:
        where_clauses.append(_format_filter(f))
    if site_code and site_code.lower() != "all":
        where_clauses.append(_site_filter(site_code, site_column))
    if metric.date_field:
        where_clauses.append(f"{date_expr} >= {start_epoch} AND {date_expr} <= {end_epoch}")
    where = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    is_date_group = group_by.endswith(("_at", "_date")) or group_by in {"begin", "end_col"}
    if is_date_group:
        x_expr = f"SUBSTRING(CAST({group_col} AS string), 1, 7)"
        order_by = "1 ASC"
    else:
        x_expr = group_col
        order_by = "2 DESC"
    return f"""{CACHE_HINT}
SELECT {x_expr} AS x, COUNT(*) AS y
FROM {table} {where}
GROUP BY 1
ORDER BY {order_by}"""


async def compute_dashboard(
    dashboard_key: str,
    project_id: int,
    session: AsyncSession,
    tenant_id: int,
    user_id: int,
    as_of: datetime | None = None,
    site_code: str | None = None,
    date_unit: str = "seconds",
    duration_unit: str = "hours",
    period_key: str | None = None,
    dimension: str = "site",
    force_refresh: bool = False,
) -> DashboardResult:
    """Compute all KPIs and charts for an ITSM dashboard preset.

    The two interactive insight presets (incident_insights,
    service_request_insights) load their source CSVs once per
    project/dashboard/dimension into an in-process snapshot and derive every
    Period/Site/Region combination from it in Python (see
    insight_snapshot.py) -- the ServiceNow VDB is CSV-backed and Teiid cannot
    push predicates into those files, so issuing one SQL statement per
    card/chart re-read the same file for every filter change. The remaining
    five KPI presets keep the per-metric Teiid path below, with metric
    queries executed concurrently and each metric's current and previous
    periods combined into a single query when the metric's shape allows it
    (see _build_combined_metric_sql).
    """
    site_column = _dimension_column(dimension)
    metrics = get_dashboard_metrics(dashboard_key)
    current_period, previous_period = _reporting_bounds(period_key, as_of)
    teiid_endpoint = await _resolve_teiid(project_id, session, tenant_id, user_id)
    is_insight_dashboard = dashboard_key in {"incident_insights", "service_request_insights"}

    if is_insight_dashboard:
        from .insight_snapshot import aggregate_insight_snapshot, load_insight_snapshot

        snapshot_key = f"{tenant_id}:{project_id}:{dashboard_key}:{dimension}"
        tables = await load_insight_snapshot(
            key=snapshot_key,
            dashboard_key=dashboard_key,
            dimension=dimension,
            run_sql=lambda sql: _run_sql(*teiid_endpoint, sql),
            force_refresh=force_refresh,
        )
        aggregation = aggregate_insight_snapshot(
            dashboard_key=dashboard_key,
            tables=tables,
            current_period=current_period,
            previous_period=previous_period,
            period_key=period_key,
            dimension=dimension,
            dimension_value=site_code,
        )
        values = [
            _assemble_metric_value(
                metric,
                *aggregation.metric_values[metric.key],
                current_period,
                previous_period,
                duration_unit,
            )
            for metric in metrics
        ]
        return DashboardResult(
            dashboard=dashboard_key,
            as_of=utc_now_iso(),
            filters={
                "site": site_code or "all",
                "dimension": dimension,
                "date_unit": date_unit,
                "durationUnit": duration_unit,
                "period": period_key or "latest_month",
            },
            metrics=values,
            charts=aggregation.charts,
            data_quality={
                "latestCompleteMonth": _month_bounds(as_of)[0].label,
                "reportingPeriod": current_period.label,
                "availableSites": aggregation.dimension_options,
                "missingMetrics": [m.key for m in metrics if m.status == "not_implemented"],
                "warnings": [],
                "executionMode": "snapshot",
            },
            insights=aggregation.insights,
        )

    # Mutated concurrently by the three phases below (asyncio is
    # single-threaded/cooperative, so concurrent list.append calls across
    # coroutines are safe); each phase's own values/charts/insights/
    # site-options are returned and assigned from asyncio.gather.
    warnings: list[str] = []

    # Bound concurrency so we do not exhaust the Teiid connection pool.  Each
    # metric may run current and previous queries concurrently, so cap at 3
    # (up to 6 connections) to leave headroom for other requests.
    max_concurrent_metrics = min(6, max(1, pool_manager.max_size // 2))
    metric_sem = asyncio.Semaphore(max_concurrent_metrics)

    async def _compute_metric(metric: MetricDefinition) -> MetricValue | BaseException:
        async with metric_sem:
            return await compute_metric(
                metric=metric,
                project_id=project_id,
                session=session,
                tenant_id=tenant_id,
                user_id=user_id,
                current_period=current_period,
                previous_period=previous_period,
                site_code=site_code,
                date_unit=date_unit,
                duration_unit=duration_unit,
                teiid_endpoint=teiid_endpoint,
                site_column=site_column,
            )

    # The remaining five KPI presets keep their existing two-metric mini
    # chart pipeline (insight presets returned above via the snapshot path).
    chart_metrics = [m for m in metrics if m.group_by]

    async def _metrics_phase() -> list[MetricValue]:
        metric_tasks = [_compute_metric(metric) for metric in metrics]
        metric_results = await asyncio.gather(*metric_tasks, return_exceptions=True)
        out: list[MetricValue] = []
        for metric, result in zip(metrics, metric_results, strict=True):
            if isinstance(result, MetricValue):
                out.append(result)
            else:
                exc = result if isinstance(result, BaseException) else Exception(result)
                logger.warning("Metric %s failed: %s", metric.key, exc)
                warnings.append(f"{metric.key}: {exc}")
                out.append(MetricValue(
                    metric_key=metric.key,
                    label=metric.label,
                    value=None,
                    display_value="—",
                    period_start=current_period.start,
                    period_end=current_period.end,
                    status="not_implemented",
                    as_of=utc_now_iso(),
                    unit=_display_unit(metric, duration_unit),
                    description=_metric_description(metric),
                    calculation=_metric_calculation(metric),
                    target=metric.target,
                ))
        return out

    async def _charts_phase() -> tuple[list[ChartResult], list[InsightSummary]]:
        if len(chart_metrics) < 2:
            return [], []

        async def _build_chart(dashboard: str, chart_metric: MetricDefinition) -> ChartResult | BaseException:
            assert chart_metric.group_by is not None
            is_date_chart = bool(
                chart_metric.group_by.endswith(("_at", "_date"))
                or chart_metric.group_by in {"begin", "end_col"}
            )
            chart_period = _rolling_month_bounds(current_period) if is_date_chart else current_period
            sql = _build_chart_sql(chart_metric, chart_period, chart_metric.group_by, site_code, date_unit, site_column)
            rows = await _run_sql(*teiid_endpoint, sql)
            x = [str(r.get("x", "")) for r in rows]
            y = [_extract_single_value([r]) for r in rows]
            title = chart_metric.chart_label or chart_metric.label
            return ChartResult(
                chart_key=f"{dashboard}_{chart_metric.key}",
                title=title,
                chart_type="line" if is_date_chart else "bar",
                x_axis_label=chart_metric.group_by,
                y_axis_label="Incidents" if dashboard == "incident" else "Records",
                series=[ChartSeries(name=title, x=x, y=y)],
                categories=x,
                unit="count",
            )

        chart_sem = asyncio.Semaphore(min(4, max(1, pool_manager.max_size // 4)))

        async def _build_chart_guarded(dashboard: str, chart_metric: MetricDefinition) -> ChartResult | BaseException:
            async with chart_sem:
                return await _build_chart(dashboard, chart_metric)

        chart_tasks = [_build_chart_guarded(dashboard_key, m) for m in chart_metrics[:2]]
        chart_results = await asyncio.gather(*chart_tasks, return_exceptions=True)
        out_charts: list[ChartResult] = []
        for chart_result in chart_results:
            if isinstance(chart_result, ChartResult):
                out_charts.append(chart_result)
            else:
                chart_exc = chart_result if isinstance(chart_result, BaseException) else Exception(chart_result)
                logger.warning("Chart build failed: %s", chart_exc)
                warnings.append(f"chart: {chart_exc}")
        return out_charts, []

    # Run both phases concurrently instead of strictly sequentially --
    # metrics and charts are otherwise independent Teiid round-trips, and
    # serializing them roughly doubles wall-clock time for no correctness
    # reason. Each phase still bounds its own sub-query concurrency via its
    # own semaphore. (Insight presets never reach here -- see the snapshot
    # path above, which has no site-options phase of its own since dimension
    # options come back from the same in-process aggregation as the charts.)
    values, (charts, insights) = await asyncio.gather(_metrics_phase(), _charts_phase())

    return DashboardResult(
        dashboard=dashboard_key,
        as_of=utc_now_iso(),
        filters={
            "site": site_code or "all",
            "dimension": dimension,
            "date_unit": date_unit,
            "durationUnit": duration_unit,
            "period": period_key or "latest_month",
        },
        metrics=values,
        charts=charts,
        data_quality={
            "latestCompleteMonth": _month_bounds(as_of)[0].label,
            "reportingPeriod": current_period.label,
            "availableSites": [],
            "missingMetrics": [m.key for m in metrics if m.status == "not_implemented"],
            "warnings": warnings,
            "executionMode": "query",
        },
        insights=insights,
    )


async def warm_itsm_dashboards_for_project(
    session: AsyncSession,
    project_id: int,
    tenant_id: int,
    user_id: int,
    presets: list[str] | None = None,
    site_code: str | None = None,
    date_unit: str = "seconds",
    duration_unit: str = "hours",
    dimension: str = "site",
) -> None:
    """Pre-compute all ITSM dashboard presets for a project to populate caches.

    This is best-effort: any failures are logged and ignored so the warm never
    blocks user traffic. Dashboards are warmed concurrently up to the limit
    supported by the Teiid connection pool, and each completed dashboard also
    populates the assembled-response cache.

    For the two insight presets, a single warm call is all that's needed:
    compute_dashboard's snapshot path (see insight_snapshot.py) loads every
    source CSV for the project/dashboard/dimension once and keeps it for five
    minutes, so every Period/Site/Region combination a user can pick is
    already covered by that one load -- there is no longer a per-site or
    per-period matrix to expand into.
    """
    presets = presets or list(list_dashboards())
    sem = asyncio.Semaphore(max(1, min(2, pool_manager.max_size // 8)))

    async def _warm_dashboard(preset: str, warm_site_code: str | None, period_key: str) -> DashboardResult | None:
        async with sem:
            try:
                async with SessionLocal() as warm_session:
                    result = await compute_dashboard(
                        dashboard_key=preset,
                        project_id=project_id,
                        session=warm_session,
                        tenant_id=tenant_id,
                        user_id=user_id,
                        site_code=warm_site_code,
                        date_unit=date_unit,
                        duration_unit=duration_unit,
                        period_key=period_key,
                        dimension=dimension,
                    )
                from .cache import make_cache_key, set_cached_dashboard

                set_cached_dashboard(
                    make_cache_key(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        dashboard_key=preset,
                        site_code=warm_site_code,
                        as_of=None,
                        duration_unit=duration_unit,
                        period_key=period_key,
                        dimension=dimension,
                    ),
                    result,
                )
                logger.info(
                    "Warmed ITSM dashboard preset %s (site=%s) for project %s",
                    preset, warm_site_code or "all", project_id,
                )
                return result
            except Exception as exc:
                logger.warning(
                    "ITSM dashboard warm failed for %s/%s (site=%s): %s",
                    project_id, preset, warm_site_code or "all", exc,
                )
                return None

    async def _warm_one(preset: str) -> None:
        period_key = "1_year" if preset in {"incident_insights", "service_request_insights"} else "latest_month"
        await _warm_dashboard(preset, site_code, period_key)

    await asyncio.gather(*[_warm_one(preset) for preset in presets], return_exceptions=True)
