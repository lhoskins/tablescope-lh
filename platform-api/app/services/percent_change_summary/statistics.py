
from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

from .models import _ZERO_TOLERANCE, SummaryCell, SummaryPeriod, SummaryRow, SummarySort, SummaryStatistics
from .period_helpers import _display_status


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


def _latest_absolute_change(
    row: SummaryRow,
    periods: list[SummaryPeriod],
) -> float | None:
    for period in reversed(periods):
        cell = row.cells.get(period.key)
        if cell and cell.percent_change_ratio is not None:
            return abs(cell.percent_change_ratio)
    return None


def _calculate_period_statistics(
    row: SummaryRow,
    periods: list[SummaryPeriod],
) -> SummaryStatistics:
    """Compute summary statistics from valid aligned period-over-period changes."""
    ratios: list[float] = []
    first_index: int | None = None
    last_index: int | None = None
    earliest_baseline: float | None = None
    latest_current: float | None = None

    for i, period in enumerate(periods):
        cell = row.cells.get(period.key)
        if cell is None or cell.percent_change_ratio is None:
            continue
        ratio = cell.percent_change_ratio
        if not math.isfinite(ratio):
            continue
        ratios.append(ratio)
        if first_index is None:
            first_index = i
            earliest_baseline = cell.previous_value
        last_index = i
        latest_current = cell.current_value

    n = len(ratios)
    stats = SummaryStatistics(valid_count=n)
    if n == 0:
        return stats

    stats.latest = ratios[-1]
    sorted_ratios = sorted(ratios)
    stats.min = sorted_ratios[0]
    stats.max = sorted_ratios[-1]
    if n % 2 == 1:
        stats.median = sorted_ratios[n // 2]
    else:
        stats.median = (sorted_ratios[n // 2 - 1] + sorted_ratios[n // 2]) / 2
    stats.average = sum(ratios) / n

    # Welford's algorithm for population variance.
    if n >= 2:
        mean = 0.0
        m2 = 0.0
        for i, x in enumerate(ratios, 1):
            delta = x - mean
            mean += delta / i
            delta2 = x - mean
            m2 += delta * delta2
        variance = m2 / n
        stats.standard_deviation = math.sqrt(max(0.0, variance))

    # Cumulative first-to-last change, only when the series is continuous and
    # the earliest baseline is non-zero.
    if (
        first_index is not None
        and last_index is not None
        and earliest_baseline is not None
        and latest_current is not None
        and math.isfinite(earliest_baseline)
        and math.isfinite(latest_current)
    ):
        discontinuous = False
        for i in range(first_index, last_index + 1):
            cell = row.cells.get(periods[i].key)
            if (
                cell is None
                or cell.percent_change_ratio is None
                or not math.isfinite(cell.percent_change_ratio)
            ):
                discontinuous = True
                break
        if (
            not discontinuous
            and abs(Decimal(str(earliest_baseline))) > _ZERO_TOLERANCE
        ):
            stats.cumulative_change = (
                latest_current - earliest_baseline
            ) / earliest_baseline

    return stats


def _sort_rows(
    rows: list[SummaryRow],
    sort: SummarySort,
    periods: list[SummaryPeriod],
) -> list[SummaryRow]:
    field = sort.field
    direction = sort.direction
    desc = direction == "desc"

    if field == "title":
        return sorted(rows, key=lambda r: r.title.lower(), reverse=desc)

    def _key(row: SummaryRow):
        value: int | float | None
        if field == "priority_score":
            value = row.priority_score
        elif field == "latest_absolute_change":
            value = _latest_absolute_change(row, periods)
        elif field.startswith("period:"):
            key = field.split(":", 1)[1]
            cell = row.cells.get(key)
            value = cell.percent_change_ratio if cell else None
        elif field.startswith("statistics:"):
            stat_field = field.split(":", 1)[1]
            stats = row.statistics
            if stats is None:
                value = None
            else:
                raw = getattr(stats, stat_field, None)
                value = raw if isinstance(raw, int | float) and not isinstance(raw, bool) else None
        else:
            value = _latest_absolute_change(row, periods)

        if value is None:
            return (float("inf"), row.title.lower())
        numeric = float(value)
        if desc:
            return (-numeric, row.title.lower())
        return (numeric, row.title.lower())

    return sorted(rows, key=_key)
