"""On-demand supporting data for ITSM KPI drawers.

Drill-down queries intentionally run only after a card is opened so richer
context does not add latency to the dashboard's first paint.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from .engine import (
    CACHE_HINT,
    _date_expression,
    _display_unit,
    _format_filter,
    _format_value,
    _metric_calculation,
    _metric_description,
    _period_epoch,
    _quote_identifier,
    _reporting_bounds,
    _resolve_teiid,
    _run_sql,
    _site_filter,
)
from .models import (
    DrilldownContributor,
    DrilldownRecord,
    MetricDefinition,
    MetricDrilldown,
)
from .registry import get_metric

logger = logging.getLogger(__name__)


def _context(metric: MetricDefinition, start: float, end: float, site_code: str | None) -> tuple[str, str, str]:
    """Return table, where clause, and contributor dimension."""
    if metric.key in {"resolution_sla", "sla_breach_rate"}:
        table = _quote_identifier("02_task_slas_CSV")
        clauses = [
            "task_type = 'Incident'",
            '"metric" IN (\'Resolution\')',
            f"unix_timestamp(CAST(end_time AS timestamp)) >= {start}",
            f"unix_timestamp(CAST(end_time AS timestamp)) <= {end}",
            _site_filter(site_code),
        ]
        if metric.key == "sla_breach_rate":
            clauses.append("CAST(has_breached AS boolean) = true")
        return table, " AND ".join(clauses), "site_code"

    table = _quote_identifier(metric.table)
    clauses = [_format_filter(item) for item in metric.filters]
    clauses.append(_site_filter(site_code))
    if metric.kind == "snapshot_eom" or metric.key == "average_open_age":
        open_expr = _date_expression(metric.date_field)
        close_expr = _date_expression(metric.close_field)
        clauses.extend(
            [
                f"{open_expr} <= {end}",
                f"({close_expr} IS NULL OR {close_expr} > {end})",
            ]
        )
        if metric.key == "backlog_older_than_30_days":
            clauses.append(f"{open_expr} <= {end} - 2592000")
    elif metric.date_field:
        date_expr = _date_expression(metric.date_field)
        clauses.extend([f"{date_expr} >= {start}", f"{date_expr} <= {end}"])

    if metric.key == "incident_volume":
        dimension = "category"
    else:
        dimension = next(
            (item for item in metric.drill_down_dimensions if item in {"site_code", "category", "priority", "assignment_group_sys_id"}),
            "site_code",
        )
    return table, " AND ".join(item for item in clauses if item), dimension


def _row_value(row: dict, key: str) -> float | None:
    raw = row.get(key, row.get(key.upper()))
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


async def compute_metric_drilldown(
    *,
    dashboard_key: str,
    metric_key: str,
    project_id: int,
    session: AsyncSession,
    tenant_id: int,
    user_id: int,
    as_of: datetime | None = None,
    site_code: str | None = None,
    duration_unit: str = "hours",
    period_key: str | None = None,
) -> MetricDrilldown:
    metric = get_metric(dashboard_key, metric_key)
    if metric is None:
        raise ValueError(f"Unknown metric: {dashboard_key}/{metric_key}")

    current_period, _ = _reporting_bounds(period_key, as_of)
    start, end = _period_epoch(current_period)
    table, where, dimension = _context(metric, start, end, site_code)
    endpoint = await _resolve_teiid(project_id, session, tenant_id, user_id)
    unit = _display_unit(metric, duration_unit)
    warnings: list[str] = []

    is_duration = metric.kind == "duration_period" and metric.numerator
    if is_duration:
        raw_value = f"AVG(CAST({_quote_identifier(metric.numerator or '')} AS double))"
    else:
        raw_value = "COUNT(DISTINCT sys_id)"
    contributor_sql = f"""{CACHE_HINT}
SELECT CAST({_quote_identifier(dimension)} AS string) AS name, {raw_value} AS value
FROM {table}
WHERE {where} AND {_quote_identifier(dimension)} IS NOT NULL
GROUP BY 1
ORDER BY 2 DESC
LIMIT 7"""

    contributors: list[DrilldownContributor] = []
    try:
        contributor_rows = await _run_sql(*endpoint, contributor_sql)
        raw_values = [_row_value(row, "value") for row in contributor_rows]
        if is_duration and unit == "hours":
            raw_values = [value / 60.0 if value is not None else None for value in raw_values]
        total = sum(value for value in raw_values if value is not None)
        for row, value in zip(contributor_rows, raw_values, strict=True):
            name = str(row.get("name", row.get("NAME", "Unspecified")))
            contributors.append(
                DrilldownContributor(
                    name=name,
                    value=value,
                    display_value=_format_value(value, metric, unit if is_duration else "count"),
                    share_percent=(100.0 * value / total) if total and value is not None and not is_duration else None,
                )
            )
    except Exception as exc:
        logger.warning("ITSM contributor drilldown failed for %s: %s", metric.key, exc)
        warnings.append("Contributor breakdown is temporarily unavailable.")

    record_fields = ["CAST(sys_id AS string) AS record_id"]
    if metric.table == "01_incidents_CSV" and metric.key not in {"resolution_sla", "sla_breach_rate"}:
        record_fields.extend(
            [
                "CAST(priority AS string) AS priority",
                "CAST(site_code AS string) AS site",
                "CAST(category AS string) AS category",
            ]
        )
    else:
        record_fields.append("CAST(site_code AS string) AS site")
    if is_duration:
        record_fields.append(f"CAST({_quote_identifier(metric.numerator or '')} AS double) AS value")
    record_order = "value DESC" if is_duration else "record_id ASC"
    record_sql = f"""{CACHE_HINT}
SELECT {', '.join(record_fields)}
FROM {table}
WHERE {where}
ORDER BY {record_order}
LIMIT 8"""

    records: list[DrilldownRecord] = []
    try:
        record_rows = await _run_sql(*endpoint, record_sql)
        for row in record_rows:
            value = _row_value(row, "value")
            if value is not None and unit == "hours":
                value /= 60.0
            records.append(
                DrilldownRecord(
                    record_id=str(row.get("record_id", row.get("RECORD_ID", ""))),
                    priority=row.get("priority", row.get("PRIORITY")),
                    site=row.get("site", row.get("SITE")),
                    category=row.get("category", row.get("CATEGORY")),
                    value=value,
                    display_value=_format_value(value, metric, unit) if value is not None else None,
                )
            )
    except Exception as exc:
        logger.warning("ITSM record drilldown failed for %s: %s", metric.key, exc)
        warnings.append("High-impact record preview is temporarily unavailable.")

    majority_share = sum(item.share_percent or 0 for item in contributors[:3]) or None
    return MetricDrilldown(
        metric_key=metric.key,
        label=metric.label,
        description=_metric_description(metric),
        calculation=_metric_calculation(metric),
        unit=unit,
        period_start=current_period.start,
        period_end=current_period.end,
        contributors_label=f"Supporting record volume by {dimension.replace('_', ' ')}",
        contributors=contributors,
        majority_share_percent=majority_share,
        records=records,
        warnings=warnings,
    )
