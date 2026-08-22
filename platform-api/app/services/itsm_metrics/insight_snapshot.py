"""Fast in-process aggregation for the two interactive ITSM insight boards.

The ServiceNow demo VDB is backed by CSV views.  Teiid cannot push predicates
or aggregates into those files, so issuing one SQL statement per card/chart
re-reads the same file for every statement.  This module loads the small set of
source rows once per project and derives period/site/region variants in Python.

The raw snapshot is deliberately short-lived and bounded.  It complements the
assembled-dashboard cache: the latter makes repeat requests instant, while this
cache makes a *new* filter combination instant after the first snapshot load.
"""

from __future__ import annotations

import asyncio
import math
from collections import Counter, OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time
from statistics import median
from threading import Lock
from time import monotonic
from typing import Any, cast

from .models import ChartResult, ChartSeries, InsightSummary, PeriodBounds

SNAPSHOT_FRESH_SECONDS = 300
MAX_SNAPSHOTS = 32

_SOURCE_SQL: dict[str, dict[str, str]] = {
    "incident_insights": {
        "incidents": """/*+ cache(pref_mem ttl:300000) */
SELECT sys_id, opened_at, resolved_at, resolution_minutes, major_incident,
       priority, state, category,
       CAST({dimension_code} AS string) AS dimension_code,
       CAST({dimension_name} AS string) AS dimension_name
FROM "01_incidents_CSV"
""",
        "slas": """/*+ cache(pref_mem ttl:300000) */
SELECT sys_id, task_type, "metric", has_breached, end_time,
       CAST({dimension_code} AS string) AS dimension_code,
       CAST({dimension_name} AS string) AS dimension_name
FROM "02_task_slas_CSV"
""",
    },
    "service_request_insights": {
        "requests": """/*+ cache(pref_mem ttl:300000) */
SELECT sys_id, requested_date, closed_at, request_fulfillment_minutes,
       fulfillment_sla_met, approval, stage, state,
       CAST({dimension_code} AS string) AS dimension_code,
       CAST({dimension_name} AS string) AS dimension_name
FROM "07_requests_CSV"
""",
        "items": """/*+ cache(pref_mem ttl:300000) */
SELECT sys_id, opened_at, closed_at, price_usd, catalog_item_name,
       CAST({dimension_code} AS string) AS dimension_code,
       CAST({dimension_name} AS string) AS dimension_name
FROM "08_requested_items_CSV"
""",
        "tasks": """/*+ cache(pref_mem ttl:300000) */
SELECT sys_id, request_item_sys_id, opened_at, closed_at, assignment_group_name,
       CAST({dimension_code} AS string) AS dimension_code,
       CAST({dimension_name} AS string) AS dimension_name
FROM "09_catalog_tasks_CSV"
""",
    },
}


@dataclass(frozen=True)
class InsightAggregation:
    metric_values: dict[str, tuple[float | None, float | None]]
    charts: list[ChartResult]
    insights: list[InsightSummary]
    dimension_options: list[dict[str, str]]


@dataclass
class _SnapshotEntry:
    tables: dict[str, list[dict[str, Any]]]
    stored_at: float


_snapshots: OrderedDict[str, _SnapshotEntry] = OrderedDict()
_snapshots_lock = Lock()
_load_locks: dict[str, asyncio.Lock] = {}


def clear_insight_snapshot_cache() -> None:
    with _snapshots_lock:
        _snapshots.clear()


def _cached_snapshot(key: str) -> dict[str, list[dict[str, Any]]] | None:
    with _snapshots_lock:
        entry = _snapshots.get(key)
        if entry is None:
            return None
        if monotonic() - entry.stored_at > SNAPSHOT_FRESH_SECONDS:
            _snapshots.pop(key, None)
            return None
        _snapshots.move_to_end(key)
        return entry.tables


def _snapshot_loaded_after(key: str, requested_at: float) -> dict[str, list[dict[str, Any]]] | None:
    """Return a snapshot refreshed by another waiter after this request began."""
    with _snapshots_lock:
        entry = _snapshots.get(key)
        if entry is None or entry.stored_at < requested_at:
            return None
        _snapshots.move_to_end(key)
        return entry.tables


def _store_snapshot(key: str, tables: dict[str, list[dict[str, Any]]]) -> None:
    with _snapshots_lock:
        _snapshots[key] = _SnapshotEntry(tables=tables, stored_at=monotonic())
        _snapshots.move_to_end(key)
        while len(_snapshots) > MAX_SNAPSHOTS:
            _snapshots.popitem(last=False)


async def load_insight_snapshot(
    *,
    key: str,
    dashboard_key: str,
    dimension: str,
    run_sql: Callable[[str], Awaitable[list[dict[str, Any]]]],
    force_refresh: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    """Load each source table once and coalesce concurrent cold requests."""
    if dashboard_key not in _SOURCE_SQL:
        raise ValueError(f"Unsupported insight snapshot: {dashboard_key}")
    requested_at = monotonic()
    if not force_refresh:
        cached = _cached_snapshot(key)
        if cached is not None:
            return cached

    lock = _load_locks.setdefault(key, asyncio.Lock())
    async with lock:
        if force_refresh:
            # Several stale assembled-dashboard keys can request a refresh at
            # once. The first waiter reloads the shared source snapshot; later
            # waiters reuse that new snapshot instead of serially reloading it.
            refreshed = _snapshot_loaded_after(key, requested_at)
            if refreshed is not None:
                return refreshed
        else:
            cached = _cached_snapshot(key)
            if cached is not None:
                return cached
        dimension_code = '"region"' if dimension == "region" else '"site_code"'
        dimension_name = '"region_name"' if dimension == "region" else '"site_name"'
        names = list(_SOURCE_SQL[dashboard_key])
        statements = [
            _SOURCE_SQL[dashboard_key][name].format(
                dimension_code=dimension_code,
                dimension_name=dimension_name,
            )
            for name in names
        ]
        rows = await asyncio.gather(*(run_sql(sql) for sql in statements))
        snapshot = dict(zip(names, rows, strict=True))
        _store_snapshot(key, snapshot)
        return snapshot


def _raw(row: dict[str, Any], key: str) -> Any:
    return row.get(key, row.get(key.upper()))


def _text(row: dict[str, Any], key: str, fallback: str = "Unspecified") -> str:
    value = _raw(row, key)
    return fallback if value is None or str(value).strip() == "" else str(value)


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "t", "yes", "y"}


def _timestamp(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, int | float):
        seconds = float(value)
        if abs(seconds) > 10_000_000_000:
            seconds /= 1000.0
        return datetime.fromtimestamp(seconds, tz=UTC)
    else:
        raw = str(value).strip()
        try:
            numeric = float(raw)
        except ValueError:
            numeric = None
        if numeric is not None:
            if abs(numeric) > 10_000_000_000:
                numeric /= 1000.0
            return datetime.fromtimestamp(numeric, tz=UTC)
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    parsed = datetime.strptime(raw, pattern)
                    break
                except ValueError:
                    continue
            else:
                return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _period_datetimes(period: PeriodBounds) -> tuple[datetime, datetime]:
    start = datetime.combine(datetime.fromisoformat(period.start).date(), time.min, tzinfo=UTC)
    end = datetime.combine(datetime.fromisoformat(period.end).date(), time.max, tzinfo=UTC)
    return start, end


def _within(value: Any, period: PeriodBounds) -> bool:
    parsed = _timestamp(value)
    if parsed is None:
        return False
    start, end = _period_datetimes(period)
    return start <= parsed <= end


def _open_at(row: dict[str, Any], opened_field: str, closed_field: str, period: PeriodBounds) -> bool:
    opened = _timestamp(_raw(row, opened_field))
    closed = _timestamp(_raw(row, closed_field))
    _, end = _period_datetimes(period)
    return opened is not None and opened <= end and (closed is None or closed > end)


def _scope_rows(rows: list[dict[str, Any]], dimension: str, value: str | None) -> list[dict[str, Any]]:
    if not value or value.lower() == "all":
        return rows
    return [row for row in rows if str(_raw(row, "dimension_code") or "") == value]


def _dimension_options(rows: list[dict[str, Any]], dimension: str) -> list[dict[str, str]]:
    options: dict[str, str] = {}
    for row in rows:
        code = str(_raw(row, "dimension_code") or "").strip()
        if not code:
            continue
        name = str(_raw(row, "dimension_name") or code).strip() or code
        options[code] = name
    return [{"code": code, "name": name} for code, name in sorted(options.items(), key=lambda item: item[1])]


def _ratio(numerator: int, denominator: int) -> float:
    return 100.0 * numerator / denominator if denominator else 0.0


def _median(rows: list[dict[str, Any]], field: str, date_field: str, period: PeriodBounds) -> float | None:
    values = [
        number
        for row in rows
        if _within(_raw(row, date_field), period)
        if (number := _number(_raw(row, field))) is not None
    ]
    return float(median(values)) if values else None


def _bucket(value: Any, daily: bool) -> str | None:
    parsed = _timestamp(value)
    if parsed is None:
        return None
    return parsed.date().isoformat() if daily else parsed.strftime("%Y-%m")


def _count_buckets(rows: list[dict[str, Any]], field: str, period: PeriodBounds, daily: bool) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        if not _within(_raw(row, field), period):
            continue
        label = _bucket(_raw(row, field), daily)
        if label:
            counts[label] += 1
    return counts


def _aligned_chart(
    *, key: str, title: str, first_name: str, first: Counter[str], second_name: str, second: Counter[str],
    y_label: str, description: str, calculation: str, metric_key: str,
) -> ChartResult:
    categories = sorted(set(first) | set(second))
    return ChartResult(
        chart_key=key,
        title=title,
        chart_type="line",
        x_axis_label="Reporting period",
        y_axis_label=y_label,
        series=[
            ChartSeries(first_name, categories, [float(first[item]) for item in categories]),
            ChartSeries(second_name, categories, [float(second[item]) for item in categories]),
        ],
        categories=categories,
        unit="count",
        description=description,
        calculation=calculation,
        drilldown_metric_key=metric_key,
        drilldown_dimension="period",
    )


def _bar_chart(
    *, key: str, title: str, series_name: str, counts: Counter[str], order: list[str] | None,
    y_label: str, description: str, calculation: str, metric_key: str, dimension: str,
    chart_type: str = "skinny_bar", limit: int | None = None,
) -> ChartResult:
    categories = order or [name for name, _ in counts.most_common(limit)]
    values = [float(counts.get(name, 0)) for name in categories]
    return ChartResult(
        chart_key=key,
        title=title,
        chart_type=chart_type,
        y_axis_label=y_label,
        series=[ChartSeries(series_name, categories, cast(list[float | None], values))],
        categories=categories,
        unit="count",
        description=description,
        calculation=calculation,
        drilldown_metric_key=metric_key,
        drilldown_dimension=dimension,
    )


def _incident_aggregation(
    tables: dict[str, list[dict[str, Any]]], current: PeriodBounds, previous: PeriodBounds,
    period_key: str | None, dimension: str, value: str | None,
) -> InsightAggregation:
    all_incidents = tables["incidents"]
    incidents = _scope_rows(all_incidents, dimension, value)
    slas = _scope_rows(tables["slas"], dimension, value)

    def backlog(period: PeriodBounds) -> float:
        return float(sum(_open_at(row, "opened_at", "resolved_at", period) for row in incidents))

    def resolution_sla(period: PeriodBounds) -> float:
        eligible = [
            row for row in slas
            if _text(row, "task_type", "") == "Incident"
            and _text(row, "metric", "") == "Resolution"
            and _within(_raw(row, "end_time"), period)
        ]
        return _ratio(sum(not _truthy(_raw(row, "has_breached")) for row in eligible), len(eligible))

    def major(period: PeriodBounds) -> float:
        return float(sum(_truthy(_raw(row, "major_incident")) and _within(_raw(row, "opened_at"), period) for row in incidents))

    metric_values = {
        "open_backlog": (backlog(current), backlog(previous)),
        "resolution_sla": (resolution_sla(current), resolution_sla(previous)),
        "median_resolution": (
            _median(incidents, "resolution_minutes", "resolved_at", current),
            _median(incidents, "resolution_minutes", "resolved_at", previous),
        ),
        "major_incidents": (major(current), major(previous)),
    }

    daily = period_key in {"30_days", "60_days", "90_days"}
    opened = _count_buckets(incidents, "opened_at", current, daily)
    resolved = _count_buckets(incidents, "resolved_at", current, daily)
    charts = [_aligned_chart(
        key="incident_insight_flow", title="Demand vs. resolution flow", first_name="Opened", first=opened,
        second_name="Resolved", second=resolved, y_label="Incidents",
        description="Incident inflow compared with completed resolution work.",
        calculation="Incidents opened and resolved, grouped by reporting interval.", metric_key="open_backlog",
    )]

    _, current_end = _period_datetimes(current)
    age_order = ["0-1 day", "2-5 days", "6-30 days", "31-90 days", "90+ days"]
    ages: Counter[str] = Counter()
    heat: Counter[tuple[str, str]] = Counter()
    categories: Counter[str] = Counter()
    for row in incidents:
        if _open_at(row, "opened_at", "resolved_at", current):
            opened_at = _timestamp(_raw(row, "opened_at"))
            age_days = (current_end - opened_at).total_seconds() / 86_400 if opened_at else 0
            age = "0-1 day" if age_days <= 1 else "2-5 days" if age_days <= 5 else "6-30 days" if age_days <= 30 else "31-90 days" if age_days <= 90 else "90+ days"
            ages[age] += 1
            heat[(_text(row, "priority"), _text(row, "state"))] += 1
        if _within(_raw(row, "opened_at"), current):
            categories[_text(row, "category")] += 1

    charts.append(_bar_chart(
        key="incident_insight_age", title="Backlog age & SLA risk", series_name="Open incidents", counts=ages,
        order=age_order, y_label="Open incidents", description="Age distribution for incidents unresolved at the reporting period end.",
        calculation="Count of unresolved incidents grouped by age at period end.", metric_key="open_backlog", dimension="age_band",
    ))
    breaches: Counter[str] = Counter(
        _text(row, "dimension_code") for row in slas
        if _text(row, "task_type", "") == "Incident" and _text(row, "metric", "") == "Resolution"
        and _truthy(_raw(row, "has_breached")) and _within(_raw(row, "end_time"), current)
    )
    charts.append(_bar_chart(
        key="incident_insight_sla_sites", title="Where SLA risk originates", series_name="Breaches", counts=breaches,
        order=None, limit=8, y_label="Breached incidents", description="Sites contributing the most completed resolution SLA breaches.",
        calculation="Breached incident resolution SLA records grouped by site.", metric_key="resolution_sla", dimension=dimension,
    ))
    states = sorted({state for _, state in heat})
    priorities = sorted({priority for priority, _ in heat})
    charts.append(ChartResult(
        chart_key="incident_insight_priority_state", title="Priority \u00d7 status concentration", chart_type="heatmap",
        x_axis_label="Status", y_axis_label="Priority",
        series=[ChartSeries(priority, states, [float(heat[(priority, state)]) for state in states]) for priority in priorities],
        categories=states, unit="count", description="Active workload concentration by incident priority and lifecycle state.",
        calculation="Count of unresolved incidents grouped by priority and state.", drilldown_metric_key="open_backlog",
        drilldown_dimension="priority_state",
    ))
    charts.append(_bar_chart(
        key="incident_insight_categories", title="Category contribution", series_name="Incidents", counts=categories,
        order=None, limit=7, y_label="Incidents", description="Highest-volume incident categories in the selected period.",
        calculation="Count of incidents opened, grouped by category.", metric_key="open_backlog", dimension="category",
    ))

    breach_total = sum(breaches.values())
    top_site, top_site_value = breaches.most_common(1)[0] if breaches else ("No site", 0)
    top_category = categories.most_common(1)[0][0] if categories else "No category"
    stale = sum(ages[name] for name in age_order[2:])
    return InsightAggregation(
        metric_values=metric_values,
        charts=charts,
        insights=[
            InsightSummary("risk", "Backlog risk", f"{stale} open incidents are older than five days.", "critical", "open_backlog"),
            InsightSummary("driver", "Primary driver", f"{top_site} contributes {round(100 * top_site_value / breach_total) if breach_total else 0}% of resolution SLA breaches.", "warning", "resolution_sla"),
            InsightSummary("action", "Recommended action", f"Review {top_category} demand and the highest-breach site before rebalancing work.", "positive", "resolution_sla"),
        ],
        dimension_options=_dimension_options(all_incidents, dimension),
    )


def _request_aggregation(
    tables: dict[str, list[dict[str, Any]]], current: PeriodBounds, previous: PeriodBounds,
    period_key: str | None, dimension: str, value: str | None,
) -> InsightAggregation:
    all_requests = tables["requests"]
    requests = _scope_rows(all_requests, dimension, value)
    items = _scope_rows(tables["items"], dimension, value)
    tasks = _scope_rows(tables["tasks"], dimension, value)
    task_counts = Counter(_text(row, "request_item_sys_id", "") for row in tasks if _text(row, "request_item_sys_id", ""))

    def backlog(period: PeriodBounds) -> float:
        return float(sum(_open_at(row, "requested_date", "closed_at", period) for row in requests))

    def request_sla(period: PeriodBounds) -> float:
        eligible = [row for row in requests if _within(_raw(row, "closed_at"), period)]
        return _ratio(sum(_truthy(_raw(row, "fulfillment_sla_met")) for row in eligible), len(eligible))

    def automated(period: PeriodBounds) -> float:
        fulfilled = [row for row in items if _within(_raw(row, "closed_at"), period)]
        return _ratio(sum(task_counts[_text(row, "sys_id", "")] <= 1 for row in fulfilled), len(fulfilled))

    metric_values = {
        "request_backlog": (backlog(current), backlog(previous)),
        "request_sla": (request_sla(current), request_sla(previous)),
        "median_fulfillment": (
            _median(requests, "request_fulfillment_minutes", "closed_at", current),
            _median(requests, "request_fulfillment_minutes", "closed_at", previous),
        ),
        "automated_fulfillment_rate": (automated(current), automated(previous)),
    }

    daily = period_key in {"30_days", "60_days", "90_days"}
    requested = _count_buckets(requests, "requested_date", current, daily)
    completed = _count_buckets(requests, "closed_at", current, daily)
    charts = [_aligned_chart(
        key="request_insight_flow", title="Demand vs. fulfillment flow", first_name="Requested", first=requested,
        second_name="Completed", second=completed, y_label="Requests",
        description="Service request demand compared with completed fulfillment work.",
        calculation="Requests submitted and completed, grouped by reporting interval.", metric_key="request_backlog",
    )]

    _, current_end = _period_datetimes(current)
    age_order = ["0-1 day", "2-5 days", "6-14 days", "15-30 days", "31+ days"]
    ages: Counter[str] = Counter()
    friction: Counter[str] = Counter()
    for row in requests:
        if not _open_at(row, "requested_date", "closed_at", current):
            continue
        requested_at = _timestamp(_raw(row, "requested_date"))
        age_days = (current_end - requested_at).total_seconds() / 86_400 if requested_at else 0
        age = "0-1 day" if age_days <= 1 else "2-5 days" if age_days <= 5 else "6-14 days" if age_days <= 14 else "15-30 days" if age_days <= 30 else "31+ days"
        ages[age] += 1
        approval = _text(row, "approval", "")
        stage = _text(row, "stage", "")
        state = _text(row, "state", "")
        source = "Pending approval" if approval not in {"Approved", "Not Required"} else "Fulfillment queue" if stage == "Fulfillment" else "Intake queue" if state == "Open" else stage or state or "Unspecified"
        friction[source] += 1

    catalog = Counter(_text(row, "catalog_item_name") for row in items if _within(_raw(row, "opened_at"), current))
    queues = Counter(_text(row, "assignment_group_name") for row in tasks if _open_at(row, "opened_at", "closed_at", current))
    charts.extend([
        _bar_chart(key="request_insight_age", title="Open work by age & state", series_name="Open requests", counts=ages,
                   order=age_order, y_label="Open requests", description="Age distribution for requests that remain unfulfilled at period end.",
                   calculation="Unfulfilled requests grouped by age at reporting period end.", metric_key="request_backlog", dimension="age_band"),
        _bar_chart(key="request_insight_friction", title="Delay source", series_name="Open requests", counts=friction,
                   order=None, y_label="Open requests", description="Current workflow states contributing to request fulfillment delay.",
                   calculation="Open requests grouped by approval and fulfillment stage.", metric_key="request_backlog", dimension="workflow_stage"),
        _bar_chart(key="request_insight_catalog", title="Catalog demand", series_name="Requested items", counts=catalog,
                   order=None, limit=7, y_label="Requested items", description="Catalog items generating the most demand in the selected period.",
                   calculation="Count of requested items grouped by catalog item.", metric_key="request_backlog", dimension="catalog_item"),
        _bar_chart(key="request_insight_queues", title="Queue load", series_name="Open catalog tasks", counts=queues,
                   order=None, limit=7, y_label="Open tasks", description="Assignment groups carrying the largest active catalog-task workload.",
                   calculation="Open catalog tasks grouped by assignment group.", metric_key="request_backlog", dimension="assignment_group"),
    ])

    friction_total = sum(friction.values())
    top_friction, top_friction_value = friction.most_common(1)[0] if friction else ("No workflow state", 0)
    top_catalog = catalog.most_common(1)[0][0] if catalog else "No catalog item"
    top_queue = queues.most_common(1)[0][0] if queues else "No assignment group"
    return InsightAggregation(
        metric_values=metric_values,
        charts=charts,
        insights=[
            InsightSummary("risk", "Fulfillment risk", f"{top_friction} represents {round(100 * top_friction_value / friction_total) if friction_total else 0}% of open request delay.", "critical", "request_backlog"),
            InsightSummary("driver", "Demand driver", f"{top_catalog} is the highest-volume catalog item in the selected period.", "warning", "request_backlog"),
            InsightSummary("action", "Recommended action", f"Review automation and capacity for {top_queue} before adding headcount.", "positive", "automated_fulfillment_rate"),
        ],
        dimension_options=_dimension_options(all_requests, dimension),
    )


def aggregate_insight_snapshot(
    *, dashboard_key: str, tables: dict[str, list[dict[str, Any]]], current_period: PeriodBounds,
    previous_period: PeriodBounds, period_key: str | None, dimension: str, dimension_value: str | None,
) -> InsightAggregation:
    if dashboard_key == "incident_insights":
        return _incident_aggregation(tables, current_period, previous_period, period_key, dimension, dimension_value)
    if dashboard_key == "service_request_insights":
        return _request_aggregation(tables, current_period, previous_period, period_key, dimension, dimension_value)
    raise ValueError(f"Unsupported insight snapshot: {dashboard_key}")
