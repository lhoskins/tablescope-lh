
from __future__ import annotations

import base64
from datetime import date, datetime, timezone
from typing import Any

from app.models.project import Project
from app.services import home_intelligence as hi
from app.services.time_series_transform import (
    TimeSeriesInterval,
    TimeSeriesRange,
    _extract_source_points,
    _infer_grain,
    _interval_coarser_or_equal,
    _supported_intervals,
    transform_card_time_series,
)

from .models import _ZERO_TOLERANCE as _ZERO_TOLERANCE
from .models import (
    PercentChangeSummaryPage,
    PercentChangeSummaryRequest,
    PercentChangeSummaryResponse,
    SummaryCell,
    SummaryRow,
    SummarySort,
    _coerce_project_id,
    _insight_id,
    logger,
)
from .models import SummaryPeriod as SummaryPeriod
from .models import SummaryStatistics as SummaryStatistics
from .period_helpers import _canonical_periods
from .period_helpers import _display_status as _display_status
from .period_helpers import _format_period_label as _format_period_label
from .period_helpers import _latest_completed_period_index as _latest_completed_period_index
from .statistics import _build_cell, _calculate_period_statistics, _sort_rows
from .statistics import _latest_absolute_change as _latest_absolute_change

"""Cross-project percent-change summary over already-authorized insight cards.

This service does not call the LLM, R, or the database per card. It reads the
user's current Business Insights snapshot, deduplicates cards, and re-runs the
same deterministic ``transform_card_time_series`` used by the single-card
percent-change view for each eligible card. All rows are aligned to one shared
period axis.
"""


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

    # Compute period statistics once on the complete authorized result set so
    # that statistic sorting and pagination are consistent.
    all_rows = [
        row.model_copy(
            update={"statistics": _calculate_period_statistics(row, periods)}
        )
        for row in all_rows
    ]

    sort = request.sort or SummarySort()
    if (
        sort.field not in {"title", "priority_score", "latest_absolute_change"}
        and not sort.field.startswith("period:")
        and not sort.field.startswith("statistics:")
    ):
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
