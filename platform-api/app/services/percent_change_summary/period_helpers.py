
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.time_series_transform import (
    TimeSeriesInterval,
    TimeSeriesRange,
    _format_period,
    _next_period_start,
    _period_end,
    _period_start,
    _range_window,
)

from .models import _ZERO_TOLERANCE, SummaryPeriod


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
    # Import date from the package so tests can monkeypatch it via
    # ``percent_change_summary.date``.
    from . import date as _summary_date

    for i in range(len(periods) - 1, -1, -1):
        if periods[i].end and periods[i].end <= str(_summary_date.today()):
            return i
    return None


def _canonical_periods(
    as_of: date,
    interval: TimeSeriesInterval,
    range_value: TimeSeriesRange,
) -> list[SummaryPeriod]:
    # The Change Summary table displays trailing periods, not a full trend --
    # 2Y widens which insights are eligible (a card only needs data somewhere
    # in the last 2 years) without doubling the column count to 24 months.
    # This is scoped to this table only: the general time-series trend chart
    # (transform_card_time_series, used by InsightTimeSeriesChart) keeps
    # showing the full 2-year history for that same range value, since a
    # trend line is exactly where 24 months of context is the point.
    window_value = (
        TimeSeriesRange.YEAR_1
        if range_value == TimeSeriesRange.YEARS_2
        else range_value
    )
    range_start, range_end, _ = _range_window(window_value, as_of)
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
