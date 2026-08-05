
from __future__ import annotations

from datetime import date
from typing import Any

from .bucketing import _aggregate_values as _aggregate_values
from .bucketing import _bucket_points, _compare_periods, _extract_source_points, _percent_label, _range_window
from .models import _ZERO_TOLERANCE as _ZERO_TOLERANCE
from .models import (
    TimeSeriesCalculation,
    TimeSeriesInterval,
    TimeSeriesMetric,
    TimeSeriesPoint,
    TimeSeriesRange,
    TimeSeriesResponse,
    _interval_coarser_or_equal,
    _supported_intervals,
)
from .models import _ParsedPeriod as _ParsedPeriod
from .models import _SourcePoint as _SourcePoint
from .models import logger as logger
from .period_arithmetic import _format_period, _infer_aggregation, _infer_grain, _period_end, _previous_period_start
from .period_arithmetic import _next_period_start as _next_period_start
from .period_arithmetic import _parse_iso_period as _parse_iso_period
from .period_arithmetic import _period_start as _period_start
from .period_arithmetic import _to_float as _to_float

"""Deterministic time-series transform for insight cards.

No LLM or R is invoked. The transform re-uses the insight's already-authorized
source points (the card's chart data), re-buckets them by the requested interval,
applies the inferred metric aggregation, and computes period-over-period percent
change on the aggregated values.
"""


def transform_card_time_series(
    card: dict[str, Any],
    insight_id: str,
    interval_value: str,
    range_value: str,
    timezone_name: str = "UTC",
    as_of: date | None = None,
) -> TimeSeriesResponse:
    """Transform a single insight card into a time-series response."""
    warnings: list[str] = []
    try:
        interval = TimeSeriesInterval(interval_value)
    except ValueError:
        return TimeSeriesResponse(
            insight_id=insight_id,
            metric=TimeSeriesMetric(name="value"),
            interval=interval_value,
            range=range_value,
            timezone=timezone_name,
            comparison_label="",
            points=[],
            calculation=TimeSeriesCalculation(interval=interval_value, range=range_value),
            warnings=[f"Unsupported interval: {interval_value}"],
            eligible=False,
        )

    try:
        range_enum = TimeSeriesRange(range_value)
    except ValueError:
        return TimeSeriesResponse(
            insight_id=insight_id,
            metric=TimeSeriesMetric(name="value"),
            interval=interval_value,
            range=range_value,
            timezone=timezone_name,
            comparison_label="",
            points=[],
            calculation=TimeSeriesCalculation(interval=interval_value, range=range_value),
            warnings=[f"Unsupported range: {range_value}"],
            eligible=False,
        )

    source_points = _extract_source_points(card)
    if not source_points:
        return TimeSeriesResponse(
            insight_id=insight_id,
            metric=TimeSeriesMetric(name="value"),
            interval=interval_value,
            range=range_value,
            timezone=timezone_name,
            comparison_label="",
            points=[],
            calculation=TimeSeriesCalculation(interval=interval_value, range=range_value),
            warnings=["Card does not contain parseable date labels."],
            eligible=False,
        )

    source_grain = _infer_grain(source_points)
    if source_grain is None:
        return TimeSeriesResponse(
            insight_id=insight_id,
            metric=TimeSeriesMetric(name="value"),
            interval=interval_value,
            range=range_value,
            timezone=timezone_name,
            comparison_label="",
            points=[],
            calculation=TimeSeriesCalculation(interval=interval_value, range=range_value),
            warnings=["Could not infer a date grain from the card labels."],
            eligible=False,
        )

    if not _interval_coarser_or_equal(source_grain, interval):
        return TimeSeriesResponse(
            insight_id=insight_id,
            metric=TimeSeriesMetric(name="value"),
            interval=interval_value,
            range=range_value,
            timezone=timezone_name,
            comparison_label="",
            points=[],
            calculation=TimeSeriesCalculation(interval=interval_value, range=range_value),
            warnings=[
                f"Selected interval ({interval.value}) is finer than the source grain "
                f"({source_grain.value}). Choose {', '.join(_supported_intervals(source_grain))} or coarser."
            ],
            eligible=False,
            source_grain=source_grain.value,
            supported_intervals=_supported_intervals(source_grain),
        )

    metric_name = str(
        card.get("valueColumn") or card.get("chart", {}).get("roles", {}).get("y") or "value"
    )
    agg, is_rate_or_ratio, value_format = _infer_aggregation(
        card.get("valueColumn"), metric_name, [sp.value for sp in source_points if sp.value is not None]
    )

    if source_grain != interval and is_rate_or_ratio:
        warnings.append(
            "Metric appears to be a rate or ratio; aggregating to a coarser interval "
            "averages period-level ratios rather than recomputing from underlying totals, "
            "so treat values and percent changes as approximate."
        )

    # Anchor the visible range at the end of the most recent source period so
    # historical data still fills the selected range. Use today (or the passed
    # as_of) for partial-period detection so the current incomplete period is
    # flagged when the source extends into the present.
    source_period_end = _period_end(max(sp.date for sp in source_points), source_grain)
    if as_of is None:
        as_of = min(date.today(), source_period_end)
    range_start, range_end, range_notes = _range_window(range_enum, source_period_end)

    buckets = _bucket_points(source_points, interval, agg, as_of)
    compared = _compare_periods(buckets, interval, is_rate_or_ratio)

    def _bucket_overlaps_range(bucket: date) -> bool:
        return bucket <= range_end and _period_end(bucket, interval) >= range_start

    points: list[TimeSeriesPoint] = []
    previous_included = 0
    for bucket, current, previous, ratio, partial, status, point_warnings in compared:
        if not _bucket_overlaps_range(bucket):
            continue
        prev_bucket = _previous_period_start(bucket, interval)
        if prev_bucket in buckets and _period_end(prev_bucket, interval) < range_start:
            previous_included += 1
        end = _period_end(bucket, interval)
        points.append(
            TimeSeriesPoint(
                label=_format_period(bucket, interval),
                period_start=bucket.isoformat(),
                period_end=end.isoformat(),
                current_value=current,
                previous_value=previous,
                percent_change_ratio=ratio,
                percent_change_label=_percent_label(ratio),
                comparison_status=status,
                partial=partial,
                warnings=point_warnings,
            )
        )

    comparison_label_map = {
        TimeSeriesInterval.DAY: "Compared with the previous day",
        TimeSeriesInterval.WEEK: "Compared with the previous week",
        TimeSeriesInterval.MONTH: "Compared with the previous month",
        TimeSeriesInterval.YEAR: "Compared with the previous year",
    }

    if is_rate_or_ratio and value_format == "percent":
        notes = ["Values are already ratios/percentages; percent change compares those period values."]
    else:
        notes = []
    notes.extend(range_notes)
    if source_grain != interval:
        notes.append(
            f"Source grain is {source_grain.value}; values were aggregated to {interval.value} "
            f"using '{agg}' aggregation."
        )

    calculation = TimeSeriesCalculation(
        interval=interval.value,
        range=range_enum.value,
        range_start=range_start.isoformat(),
        range_end=range_end.isoformat(),
        as_of=as_of.isoformat(),
        previous_periods_included=previous_included,
        notes=notes,
    )

    metric = TimeSeriesMetric(
        name=metric_name,
        aggregation=agg,
        is_rate_or_ratio=is_rate_or_ratio,
        value_format=value_format,
    )

    return TimeSeriesResponse(
        insight_id=insight_id,
        metric=metric,
        interval=interval.value,
        range=range_enum.value,
        timezone=timezone_name,
        comparison_label=comparison_label_map[interval],
        points=points,
        calculation=calculation,
        warnings=warnings,
        eligible=True,
        source_grain=source_grain.value,
        supported_intervals=_supported_intervals(source_grain),
    )
