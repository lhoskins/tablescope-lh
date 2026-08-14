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
from typing import Any, cast

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.routes.dashboards_widget_query import _run_widget_sql
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
from .registry import get_dashboard_metrics

logger = logging.getLogger(__name__)


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
            return expr
        return f"SELECT {expr} AS metric_value"

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
        return f"SELECT {select} AS metric_value FROM {table} {where}"

    if metric.kind == "snapshot_eom":
        open_field = metric.date_field or "opened_at"
        close_field = getattr(metric, "close_field", "resolved_at")
        open_expr = _date_expression(open_field, date_unit)
        close_expr = _date_expression(close_field, date_unit)
        where_clauses.append(f"{open_expr} <= {end_epoch}")
        where_clauses.append(f"({close_expr} IS NULL OR {close_expr} > {end_epoch})")
        if metric.state_field:
            states = [f"'{s}'" for s in (metric.open_states or ["New", "In Progress", "On Hold"])]
            state_col = _quote_identifier(metric.state_field)
            where_clauses.append(f"{state_col} IN ({', '.join(states)})")
        select = "COUNT(DISTINCT sys_id)"
        where = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        return f"SELECT {select} AS metric_value FROM {table} {where}"

    if metric.kind == "duration_period":
        duration_col = metric.numerator or "resolution_minutes"
        where_clauses.append(f"{date_expr} >= {start_epoch} AND {date_expr} <= {end_epoch}")
        where_clauses.append(f"{_quote_identifier(duration_col)} IS NOT NULL")
        select = f"AVG(CAST({_quote_identifier(duration_col)} AS double))"
        where = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        return f"SELECT {select} AS metric_value FROM {table} {where}"

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
        sql = f"""SELECT CASE WHEN {den_expr} > 0 THEN CAST(100.0 * CAST({num_expr} AS double) / {den_expr} AS double) ELSE 0 END AS metric_value
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


def _format_value(value: float | None, metric: MetricDefinition) -> str:
    if value is None:
        return "—"
    if math.isnan(value) or math.isinf(value):
        return "—"
    if metric.unit == "percent":
        return f"{value:.{metric.precision}f}%"
    if metric.unit == "count":
        return f"{int(value):,}"
    if metric.unit in ("minutes", "hours"):
        return f"{value:.{metric.precision}f}"
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

    current_value = _extract_single_value(current_rows)
    previous_value = _extract_single_value(previous_rows)

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
        display_value=_format_value(current_value, metric),
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
    return f"""SELECT {x_expr} AS x, COUNT(DISTINCT sys_id) AS y
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

    metric_tasks = [
        compute_metric(
            metric=metric,
            project_id=project_id,
            session=session,
            tenant_id=tenant_id,
            user_id=user_id,
            current_period=current_period,
            previous_period=previous_period,
            site_code=site_code,
            date_unit=date_unit,
            teiid_endpoint=teiid_endpoint,
        )
        for metric in metrics
    ]
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
            ))

    # Build charts from the first two metrics that define a group_by.
    chart_metrics = [m for m in metrics if m.group_by]
    charts: list[ChartResult] = []
    if len(chart_metrics) >= 2:
        async def _build_chart(chart_metric: MetricDefinition) -> ChartResult | BaseException:
            assert chart_metric.group_by is not None
            sql = _build_chart_sql(chart_metric, current_period, chart_metric.group_by, site_code, date_unit)
            rows = await _run_sql(*teiid_endpoint, sql)
            x = [str(r.get("x", "")) for r in rows]
            y = [_extract_single_value([r]) for r in rows]
            is_date_chart = bool(
                chart_metric.group_by.endswith(("_at", "_date"))
                or chart_metric.group_by in {"begin", "end_col"}
            )
            return ChartResult(
                chart_key=f"{dashboard_key}_{chart_metric.key}",
                title=chart_metric.label,
                chart_type="line" if is_date_chart else "bar",
                x_axis_label=chart_metric.group_by,
                y_axis_label="Count",
                series=[ChartSeries(name=chart_metric.label, x=x, y=y)],
                categories=x,
            )

        chart_tasks = [_build_chart(m) for m in chart_metrics[:2]]
        chart_results = await asyncio.gather(*chart_tasks, return_exceptions=True)
        for result in chart_results:
            if isinstance(result, ChartResult):
                charts.append(result)
            else:
                exc = result if isinstance(result, BaseException) else Exception(result)
                logger.warning("Chart build failed: %s", exc)
                warnings.append(f"chart: {exc}")

    return DashboardResult(
        dashboard=dashboard_key,
        as_of=utc_now_iso(),
        filters={"site": site_code or "all", "date_unit": date_unit},
        metrics=values,
        charts=charts,
        data_quality={
            "latestCompleteMonth": current_period.label,
            "missingMetrics": [m.key for m in metrics if m.status == "not_implemented"],
            "warnings": warnings,
        },
    )
