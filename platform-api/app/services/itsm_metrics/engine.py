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
    MetricDefinition,
    MetricValue,
    PeriodBounds,
)
from .registry import get_dashboard_metrics, list_dashboards

logger = logging.getLogger(__name__)

CACHE_HINT = "/*+ cache(pref_mem ttl:300000) */"

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
    return f"{_quote_identifier(site_column)} = '{site_code}'"


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
        where_clauses.append(_site_filter(site_code))

    # Custom value expression wins.
    if metric.value_expression:
        expr = metric.value_expression.format(
            table=table,
            start=start_epoch,
            end=end_epoch,
            start_iso=repr(period.start),
            end_iso=repr(period.end),
            site_filter=_site_filter(site_code),
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
            select = f"COUNT(DISTINCT {target_col})"
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
        select = "COUNT(DISTINCT sys_id)"
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


def _metric_sql_safe(metric: MetricDefinition, period: PeriodBounds, site_code: str | None, date_unit: str) -> str:
    try:
        return _build_metric_sql(metric, period, site_code, date_unit)
    except Exception as exc:
        logger.warning("SQL build failed for %s: %s", metric.key, exc)
        return "SELECT NULL AS metric_value"


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
) -> MetricValue:
    """Run a metric for current and previous month and assemble a KPI card value."""
    if teiid_endpoint is None:
        database, host, port = await _resolve_teiid(project_id, session, tenant_id, user_id)
    else:
        database, host, port = teiid_endpoint

    current_sql = _metric_sql_safe(metric, current_period, site_code, date_unit)
    previous_sql = _metric_sql_safe(metric, previous_period, site_code, date_unit)

    current_rows, previous_rows = await asyncio.gather(
        _run_sql(database, host, port, current_sql),
        _run_sql(database, host, port, previous_sql),
    )

    current_value = _convert_duration(_extract_metric_value(current_rows, metric), metric.unit, duration_unit)
    previous_value = _convert_duration(_extract_metric_value(previous_rows, metric), metric.unit, duration_unit)
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


def _build_chart_sql(
    metric: MetricDefinition,
    period: PeriodBounds,
    group_by: str,
    site_code: str | None,
    date_unit: str,
) -> str:
    table = _quote_identifier(metric.table)
    start_epoch, end_epoch = _period_epoch(period)
    date_expr = _date_expression(metric.date_field, date_unit)
    group_col = _quote_identifier(group_by)
    where_clauses: list[str] = []
    for f in metric.filters:
        where_clauses.append(_format_filter(f))
    if site_code and site_code.lower() != "all":
        where_clauses.append(_site_filter(site_code))
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
SELECT {x_expr} AS x, COUNT(DISTINCT sys_id) AS y
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
) -> DashboardResult:
    """Compute all KPIs and charts for an ITSM dashboard preset.

    Metric queries are executed concurrently to keep dashboard load times under
    control; each metric still runs current and previous periods independently.
    """
    metrics = get_dashboard_metrics(dashboard_key)
    current_period, previous_period = _month_bounds(as_of)
    teiid_endpoint = await _resolve_teiid(project_id, session, tenant_id, user_id)

    values: list[MetricValue] = []
    warnings: list[str] = []

    # Bound concurrency so we do not exhaust the Teiid connection pool.  Each
    # metric may run current and previous queries concurrently, so cap at 3
    # (up to 6 connections) to leave headroom for other requests.
    max_concurrent_metrics = min(3, max(1, pool_manager.max_size // 2))
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
            )

    metric_tasks = [_compute_metric(metric) for metric in metrics]
    metric_results = await asyncio.gather(*metric_tasks, return_exceptions=True)
    for metric, result in zip(metrics, metric_results, strict=True):
        if isinstance(result, MetricValue):
            values.append(result)
        else:
            exc = result if isinstance(result, BaseException) else Exception(result)
            logger.warning("Metric %s failed: %s", metric.key, exc)
            warnings.append(f"{metric.key}: {exc}")
            values.append(MetricValue(
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

    # Build charts from the first two metrics that define a group_by.
    chart_metrics = [m for m in metrics if m.group_by]
    charts: list[ChartResult] = []
    if len(chart_metrics) >= 2:
        async def _build_chart(dashboard: str, chart_metric: MetricDefinition) -> ChartResult | BaseException:
            assert chart_metric.group_by is not None
            is_date_chart = bool(
                chart_metric.group_by.endswith(("_at", "_date"))
                or chart_metric.group_by in {"begin", "end_col"}
            )
            chart_period = _rolling_month_bounds(current_period) if is_date_chart else current_period
            sql = _build_chart_sql(chart_metric, chart_period, chart_metric.group_by, site_code, date_unit)
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

        chart_sem = asyncio.Semaphore(min(2, max(1, pool_manager.max_size // 4)))

        async def _build_chart_guarded(dashboard: str, chart_metric: MetricDefinition) -> ChartResult | BaseException:
            async with chart_sem:
                return await _build_chart(dashboard, chart_metric)

        chart_tasks = [_build_chart_guarded(dashboard_key, m) for m in chart_metrics[:2]]
        chart_results = await asyncio.gather(*chart_tasks, return_exceptions=True)
        for chart_result in chart_results:
            if isinstance(chart_result, ChartResult):
                charts.append(chart_result)
            else:
                exc = chart_result if isinstance(chart_result, BaseException) else Exception(chart_result)
                logger.warning("Chart build failed: %s", exc)
                warnings.append(f"chart: {exc}")

    return DashboardResult(
        dashboard=dashboard_key,
        as_of=utc_now_iso(),
        filters={"site": site_code or "all", "date_unit": date_unit, "durationUnit": duration_unit},
        metrics=values,
        charts=charts,
        data_quality={
            "latestCompleteMonth": current_period.label,
            "missingMetrics": [m.key for m in metrics if m.status == "not_implemented"],
            "warnings": warnings,
        },
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
) -> None:
    """Pre-compute all ITSM dashboard presets for a project to populate Teiid caches.

    This is best-effort: any failures are logged and ignored so the warm never
    blocks user traffic. Dashboards are warmed concurrently up to the limit
    supported by the Teiid connection pool, and each completed dashboard also
    populates the assembled-response cache.
    """
    presets = presets or list(list_dashboards())
    sem = asyncio.Semaphore(max(1, min(2, pool_manager.max_size // 8)))

    async def _warm_one(preset: str) -> None:
        async with sem:
            try:
                async with SessionLocal() as warm_session:
                    result = await compute_dashboard(
                        dashboard_key=preset,
                        project_id=project_id,
                        session=warm_session,
                        tenant_id=tenant_id,
                        user_id=user_id,
                        site_code=site_code,
                        date_unit=date_unit,
                        duration_unit=duration_unit,
                    )
                from .cache import make_cache_key, set_cached_dashboard

                set_cached_dashboard(
                    make_cache_key(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        dashboard_key=preset,
                        site_code=site_code,
                        as_of=None,
                        duration_unit=duration_unit,
                    ),
                    result,
                )
                logger.info("Warmed ITSM dashboard preset %s for project %s", preset, project_id)
            except Exception as exc:
                logger.warning("ITSM dashboard warm failed for %s/%s: %s", project_id, preset, exc)

    await asyncio.gather(*[_warm_one(preset) for preset in presets], return_exceptions=True)
