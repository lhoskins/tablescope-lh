"""Cross-project percent-change summary over already-authorized insight cards.

This service does not call the LLM, R, or the database per card. It reads the
user's current Business Insights snapshot, deduplicates cards, and re-runs the
same deterministic ``transform_card_time_series`` used by the single-card
percent-change view for each eligible card. All rows are aligned to one shared
period axis.
"""

from __future__ import annotations

import base64
import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from app.models.project import Project
from app.services import home_intelligence as hi
from app.services.time_series_transform import (
    TimeSeriesInterval,
    TimeSeriesRange,
    _extract_source_points,
    _format_period,
    _infer_grain,
    _interval_coarser_or_equal,
    _next_period_start,
    _period_end,
    _period_start,
    _range_window,
    _supported_intervals,
    transform_card_time_series,
)

logger = logging.getLogger(__name__)

_ZERO_TOLERANCE = Decimal("1E-9")


class SummarySort(BaseModel):
    field: str = "latest_absolute_change"
    direction: str = "desc"


class PercentChangeSummaryRequest(BaseModel):
    project_ids: list[int] = []
    interval: str = "month"
    range: str = "1y"
    search: str | None = None
    sort: SummarySort | None = None
    cursor: str | None = None
    page_size: int = 25


class SummaryPeriod(BaseModel):
    key: str
    label: str
    start: str
    end: str
    is_latest: bool = False


class SummaryCell(BaseModel):
    current_value: float | None = None
    previous_value: float | None = None
    percent_change_ratio: float | None = None
    status: str = "unavailable"  # display status: positive | negative | zero | unavailable
    comparison_status: str = "unavailable"
    partial: bool = False
    warnings: list[str] = Field(default_factory=list)


class SummaryRow(BaseModel):
    insight_id: str
    title: str
    project_id: int
    project_name: str
    project_color: str | None = None
    priority_score: float | None = None
    source_grain: str | None = None
    supported_intervals: list[str] = Field(default_factory=list)
    data_through: str | None = None
    cells: dict[str, SummaryCell] = Field(default_factory=dict)


class PercentChangeSummaryPage(BaseModel):
    page_size: int
    total_in_scope: int
    total_eligible: int
    total_excluded: int
    next_cursor: str | None = None


class PercentChangeSummaryResponse(BaseModel):
    schema_version: int = 1
    interval: str
    range: str
    as_of: str
    comparison_label: str
    periods: list[SummaryPeriod]
    rows: list[SummaryRow]
    interval_support_counts: dict[str, int]
    page: PercentChangeSummaryPage
    excluded_by_reason: dict[str, int]
    warnings: list[str] = Field(default_factory=list)


def _coerce_project_id(value: Any) -> int | None:
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _insight_id(card: dict[str, Any]) -> str:
    return str(card.get("insightId") or card.get("id") or "")


def _format_period_label(d: date, interval: TimeSeriesInterval) -> str:
    if interval == TimeSeriesInterval.DAY:
        return d.strftime("%b %-d, %Y")
    if interval == TimeSeriesInterval.WEEK:
        return f"{_format_period(d, interval)}"
    if interval == TimeSeriesInterval.MONTH:
        return d.strftime("%b %Y")
    if interval == TimeSeriesInterval.YEAR:
        return str(d.year)
    return _format_period(d, interval)


def _latest_completed_period_index(periods: list[SummaryPeriod]) -> int | None:
    for i in range(len(periods) - 1, -1, -1):
        if periods[i].end and periods[i].end <= str(date.today()):
            return i
    return None


def _canonical_periods(
    as_of: date,
    interval: TimeSeriesInterval,
    range_value: TimeSeriesRange,
) -> list[SummaryPeriod]:
    range_start, range_end, _ = _range_window(range_value, as_of)
    d = _period_start(range_start, interval)
    periods: list[SummaryPeriod] = []
    while d <= range_end:
        end = _period_end(d, interval)
        key = _format_period(d, interval)
        periods.append(
            SummaryPeriod(
                key=key,
                label=_format_period_label(d, interval),
                start=d.isoformat(),
                end=end.isoformat(),
            )
        )
        d = _next_period_start(d, interval)
    latest_idx = _latest_completed_period_index(periods)
    if latest_idx is not None:
        periods[latest_idx].is_latest = True
    return periods


def _display_status(ratio: float | None, comparison_status: str) -> str:
    if ratio is None:
        return "unavailable"
    if abs(Decimal(str(ratio))) <= _ZERO_TOLERANCE:
        return "zero"
    if ratio > 0:
        return "positive"
    return "negative"


def _build_cell(point: Any) -> SummaryCell:
    ratio = point.percent_change_ratio
    status = _display_status(ratio, point.comparison_status)
    return SummaryCell(
        current_value=point.current_value,
        previous_value=point.previous_value,
        percent_change_ratio=ratio,
        status=status,
        comparison_status=point.comparison_status,
        partial=point.partial,
        warnings=point.warnings or [],
    )


def _evaluate_card(
    card: dict[str, Any],
    project_id: int,
    project_name: str,
    project_color: str | None,
    interval: TimeSeriesInterval,
    range_value: TimeSeriesRange,
    as_of: date,
) -> tuple[SummaryRow, str | None, list[str]]:
    """Return (row, exclusion_reason or None, supported_intervals)."""
    insight_id = _insight_id(card)
    title = str(card.get("title") or "")
    priority = card.get("priorityScore") or card.get("confidenceScore") or None
    if priority is not None:
        try:
            priority = float(priority)
        except (ValueError, TypeError):
            priority = None

    chart = card.get("chart")
    if not chart or not isinstance(chart, dict):
        return (
            SummaryRow(
                insight_id=insight_id,
                title=title,
                project_id=project_id,
                project_name=project_name,
                project_color=project_color,
                priority_score=priority,
            ),
            "unavailable_source_chart_data",
            [],
        )

    source_points = _extract_source_points(card)
    if not source_points:
        return (
            SummaryRow(
                insight_id=insight_id,
                title=title,
                project_id=project_id,
                project_name=project_name,
                project_color=project_color,
                priority_score=priority,
            ),
            "not_time_series",
            [],
        )

    data_through = max((sp.date for sp in source_points), default=None)
    data_through_str = data_through.isoformat() if data_through else None

    source_grain = _infer_grain(source_points)
    supported = _supported_intervals(source_grain) if source_grain else []

    has_numeric = any(sp.value is not None for sp in source_points)
    if not has_numeric:
        return (
            SummaryRow(
                insight_id=insight_id,
                title=title,
                project_id=project_id,
                project_name=project_name,
                project_color=project_color,
                priority_score=priority,
                source_grain=source_grain.value if source_grain else None,
                supported_intervals=supported,
                data_through=data_through_str,
            ),
            "no_numeric_measure",
            supported,
        )

    if len(source_points) < 2:
        return (
            SummaryRow(
                insight_id=insight_id,
                title=title,
                project_id=project_id,
                project_name=project_name,
                project_color=project_color,
                priority_score=priority,
                source_grain=source_grain.value if source_grain else None,
                supported_intervals=supported,
                data_through=data_through_str,
            ),
            "insufficient_periods",
            supported,
        )

    if source_grain is None or not _interval_coarser_or_equal(source_grain, interval):
        return (
            SummaryRow(
                insight_id=insight_id,
                title=title,
                project_id=project_id,
                project_name=project_name,
                project_color=project_color,
                priority_score=priority,
                source_grain=source_grain.value if source_grain else None,
                supported_intervals=supported,
                data_through=data_through_str,
            ),
            "unsupported_source_grain",
            supported,
        )

    response = transform_card_time_series(
        card,
        insight_id,
        interval.value,
        range_value.value,
        "UTC",
        as_of=as_of,
    )

    if not response.eligible:
        return (
            SummaryRow(
                insight_id=insight_id,
                title=title,
                project_id=project_id,
                project_name=project_name,
                project_color=project_color,
                priority_score=priority,
                source_grain=source_grain.value if source_grain else None,
                supported_intervals=supported,
                data_through=data_through_str,
            ),
            "unsupported_source_grain",
            supported,
        )

    point_by_key: dict[str, Any] = {p.label: p for p in response.points}
    cells: dict[str, SummaryCell] = {}
    for period in _canonical_periods(as_of, interval, range_value):
        if period.key in point_by_key:
            cells[period.key] = _build_cell(point_by_key[period.key])
        else:
            cells[period.key] = SummaryCell(
                comparison_status="unavailable",
                warnings=["No data for this period."],
            )

    return (
        SummaryRow(
            insight_id=insight_id,
            title=title,
            project_id=project_id,
            project_name=project_name,
            project_color=project_color,
            priority_score=priority,
            source_grain=source_grain.value if source_grain else None,
            supported_intervals=supported,
            data_through=data_through_str,
            cells=cells,
        ),
        None,
        supported,
    )


def _latest_absolute_change(row: SummaryRow, periods: list[SummaryPeriod]) -> float:
    for period in reversed(periods):
        cell = row.cells.get(period.key)
        if cell and cell.percent_change_ratio is not None:
            return abs(cell.percent_change_ratio)
    return -1.0


def _sort_rows(
    rows: list[SummaryRow],
    sort: SummarySort,
    periods: list[SummaryPeriod],
) -> list[SummaryRow]:
    field = sort.field
    direction = sort.direction
    desc = direction == "desc"

    def _key(row: SummaryRow):
        if field == "title":
            return row.title.lower()
        if field == "priority_score":
            return row.priority_score if row.priority_score is not None else -1.0
        if field == "latest_absolute_change":
            return _latest_absolute_change(row, periods)
        if field.startswith("period:"):
            key = field.split(":", 1)[1]
            cell = row.cells.get(key)
            ratio = cell.percent_change_ratio if cell else None
            if ratio is None:
                return float("-inf") if desc else float("inf")
            return ratio
        return _latest_absolute_change(row, periods)

    return sorted(rows, key=_key, reverse=desc)


def build_percent_change_summary(
    projects: list[Project],
    snapshot_payload: dict[str, Any],
    request: PercentChangeSummaryRequest,
) -> PercentChangeSummaryResponse:
    started_at = datetime.now(timezone.utc)  # noqa: UP017

    try:
        interval = TimeSeriesInterval(request.interval)
    except ValueError as exc:
        raise ValueError(f"Unsupported interval: {request.interval}") from exc

    try:
        range_value = TimeSeriesRange(request.range)
    except ValueError as exc:
        raise ValueError(f"Unsupported range: {request.range}") from exc

    as_of = datetime.now(timezone.utc).date()  # noqa: UP017
    periods = _canonical_periods(as_of, interval, range_value)

    allowed_ids = {p.id for p in projects}
    allowed_names = {p.id: p.name for p in projects}
    allowed_colors: dict[int, str | None] = {p.id: hi.project_color(p.id) for p in projects}

    results = snapshot_payload.get("results") or []
    if not isinstance(results, list):
        results = []

    candidates: list[tuple[SummaryRow, str | None, list[str]]] = []
    seen: set[str] = set()
    warnings: list[str] = []

    for project_result in results:
        if not isinstance(project_result, dict):
            continue
        raw_project_id = _coerce_project_id(project_result.get("projectId"))
        if raw_project_id is None or raw_project_id not in allowed_ids:
            continue
        project_name = project_result.get("projectName") or allowed_names.get(raw_project_id, "")
        project_color = project_result.get("projectColor") or allowed_colors.get(raw_project_id)
        insights = project_result.get("insights") or []
        if not isinstance(insights, list):
            continue

        for card in insights:
            if not isinstance(card, dict):
                continue
            insight_id = _insight_id(card)
            if not insight_id:
                continue
            if insight_id in seen:
                candidates.append(
                    (
                        SummaryRow(
                            insight_id=insight_id,
                            title=str(card.get("title") or ""),
                            project_id=raw_project_id,
                            project_name=project_name,
                            project_color=project_color,
                        ),
                        "duplicate_card",
                        [],
                    )
                )
                continue
            seen.add(insight_id)
            candidates.append(
                _evaluate_card(
                    card,
                    raw_project_id,
                    project_name,
                    project_color,
                    interval,
                    range_value,
                    as_of,
                )
            )

    search = (request.search or "").strip().lower()
    if search:
        candidates = [
            (row, reason, supported)
            for row, reason, supported in candidates
            if search in row.title.lower() or search in row.project_name.lower()
        ]

    interval_support_counts: dict[str, int] = {
        "day": 0,
        "week": 0,
        "month": 0,
        "year": 0,
    }
    excluded_by_reason: dict[str, int] = {}
    all_rows: list[SummaryRow] = []

    for row, reason, supported in candidates:
        for iv in supported:
            if iv in interval_support_counts:
                interval_support_counts[iv] += 1
        if reason:
            excluded_by_reason[reason] = excluded_by_reason.get(reason, 0) + 1
        else:
            all_rows.append(row)

    total_in_scope = len(candidates)
    total_eligible = len(all_rows)
    total_excluded = total_in_scope - total_eligible

    sort = request.sort or SummarySort()
    if sort.field not in {"title", "priority_score", "latest_absolute_change"} and not sort.field.startswith("period:"):
        sort = SummarySort(field="latest_absolute_change", direction="desc")
    all_rows = _sort_rows(all_rows, sort, periods)

    page_size = max(1, min(100, request.page_size))
    try:
        offset = int(base64.b64decode(request.cursor or "").decode()) if request.cursor else 0
    except Exception:
        offset = 0
    offset = max(0, offset)

    page_rows = all_rows[offset : offset + page_size]
    next_cursor: str | None = None
    if offset + page_size < total_eligible:
        next_cursor = base64.b64encode(str(offset + page_size).encode()).decode()

    comparison_label_map = {
        TimeSeriesInterval.DAY: "Compared with the previous day",
        TimeSeriesInterval.WEEK: "Compared with the previous week",
        TimeSeriesInterval.MONTH: "Compared with the previous month",
        TimeSeriesInterval.YEAR: "Compared with the previous year",
    }

    elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()  # noqa: UP017
    logger.info(
        "percent-change-summary finished",
        extra={
            "elapsed_seconds": elapsed,
            "total_in_scope": total_in_scope,
            "total_eligible": total_eligible,
            "total_excluded": total_excluded,
            "interval": interval.value,
            "range": range_value.value,
            "page_size": page_size,
        },
    )

    return PercentChangeSummaryResponse(
        interval=interval.value,
        range=range_value.value,
        as_of=as_of.isoformat(),
        comparison_label=comparison_label_map[interval],
        periods=periods,
        rows=page_rows,
        interval_support_counts=interval_support_counts,
        page=PercentChangeSummaryPage(
            page_size=page_size,
            total_in_scope=total_in_scope,
            total_eligible=total_eligible,
            total_excluded=total_excluded,
            next_cursor=next_cursor,
        ),
        excluded_by_reason=excluded_by_reason,
        warnings=warnings,
    )
