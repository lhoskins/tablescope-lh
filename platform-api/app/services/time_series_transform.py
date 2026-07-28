"""Deterministic time-series transform for insight cards.

No LLM or R is invoked. The transform re-uses the insight's already-authorized
source points (the card's chart data), re-buckets them by the requested interval,
applies the inferred metric aggregation, and computes period-over-period percent
change on the aggregated values.
"""

from __future__ import annotations

import calendar
import logging
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from statistics import mean
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_ZERO_TOLERANCE = Decimal("1E-9")


class TimeSeriesInterval(str, Enum):  # noqa: UP042
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"


class TimeSeriesRange(str, Enum):  # noqa: UP042
    DAYS_7 = "7d"
    DAYS_30 = "30d"
    DAYS_90 = "90d"
    YEAR_1 = "1y"
    YEARS_2 = "2y"


class TimeSeriesMetric(BaseModel):
    name: str
    aggregation: str | None = None
    is_rate_or_ratio: bool = False
    value_format: str | None = None


class TimeSeriesPoint(BaseModel):
    label: str
    period_start: str
    period_end: str
    current_value: float | None = None
    previous_value: float | None = None
    percent_change_ratio: float | None = None
    percent_change_label: str | None = None
    comparison_status: str = "valid"
    partial: bool = False
    warnings: list[str] = Field(default_factory=list)


class TimeSeriesCalculation(BaseModel):
    formula: str = "((current_value - previous_value) / previous_value) * 100"
    interval: str
    range: str
    range_start: str | None = None
    range_end: str | None = None
    as_of: str | None = None
    previous_periods_included: int = 0
    notes: list[str] = Field(default_factory=list)


class TimeSeriesResponse(BaseModel):
    insight_id: str
    metric: TimeSeriesMetric
    interval: str
    range: str
    timezone: str
    comparison_label: str
    points: list[TimeSeriesPoint]
    calculation: TimeSeriesCalculation
    warnings: list[str] = Field(default_factory=list)
    eligible: bool = True
    source_grain: str | None = None
    supported_intervals: list[str] = Field(default_factory=list)


class _ParsedPeriod:
    __slots__ = ("date", "grain", "raw")

    def __init__(self, d: date, grain: TimeSeriesInterval, raw: str) -> None:
        self.date = d
        self.grain = grain
        self.raw = raw


class _SourcePoint:
    __slots__ = ("date", "label", "value", "value2")

    def __init__(
        self,
        d: date,
        value: float | None,
        label: str,
        value2: float | None = None,
    ) -> None:
        self.date = d
        self.value = value
        self.label = label
        self.value2 = value2


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").replace("$", "").replace("%", "").strip())
    except (ValueError, TypeError):
        return None


def _parse_iso_period(raw: Any) -> _ParsedPeriod | None:
    """Parse a period label into a date and infer its grain."""
    text = str(raw).strip()
    # ISO week: 2024-W01
    m = re.match(r"^(\d{4})-W(\d{2})$", text)
    if m:
        year, week = int(m.group(1)), int(m.group(2))
        try:
            d = date.fromisocalendar(year, week, 1)
            return _ParsedPeriod(d, TimeSeriesInterval.WEEK, text)
        except ValueError:
            return None
    # Year-month-day
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", text)
    if m:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return _ParsedPeriod(date(year, month, day), TimeSeriesInterval.DAY, text)
        except ValueError:
            return None
    # Year-month
    m = re.match(r"^(\d{4})-(\d{2})$", text)
    if m:
        year, month = int(m.group(1)), int(m.group(2))
        try:
            return _ParsedPeriod(date(year, month, 1), TimeSeriesInterval.MONTH, text)
        except ValueError:
            return None
    # Year quarter: 2024-Q1
    m = re.match(r"^(\d{4})-Q(\d)$", text)
    if m:
        year, q = int(m.group(1)), int(m.group(2))
        month = (q - 1) * 3 + 1
        try:
            return _ParsedPeriod(date(year, month, 1), TimeSeriesInterval.MONTH, text)
        except ValueError:
            return None
    # Year only
    m = re.match(r"^(\d{4})$", text)
    if m:
        year = int(m.group(1))
        return _ParsedPeriod(date(year, 1, 1), TimeSeriesInterval.YEAR, text)
    # Try a few common human formats (MM/DD/YYYY, DD/MM/YYYY, Mon YYYY)
    for fmt in ("%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y", "%b %Y", "%B %Y"):
        try:
            dt = datetime.strptime(text, fmt)
            grain = TimeSeriesInterval.MONTH if fmt in ("%b %Y", "%B %Y") else TimeSeriesInterval.DAY
            return _ParsedPeriod(dt.date(), grain, text)
        except ValueError:
            continue
    return None


def _period_start(d: date, interval: TimeSeriesInterval) -> date:
    if interval == TimeSeriesInterval.DAY:
        return d
    if interval == TimeSeriesInterval.WEEK:
        return d - timedelta(days=d.weekday())
    if interval == TimeSeriesInterval.MONTH:
        return date(d.year, d.month, 1)
    if interval == TimeSeriesInterval.YEAR:
        return date(d.year, 1, 1)
    return d


def _period_end(d: date, interval: TimeSeriesInterval) -> date:
    start = _period_start(d, interval)
    if interval == TimeSeriesInterval.DAY:
        return start
    if interval == TimeSeriesInterval.WEEK:
        return start + timedelta(days=6)
    if interval == TimeSeriesInterval.MONTH:
        last_day = calendar.monthrange(start.year, start.month)[1]
        return date(start.year, start.month, last_day)
    if interval == TimeSeriesInterval.YEAR:
        return date(start.year, 12, 31)
    return start


def _previous_period_start(d: date, interval: TimeSeriesInterval) -> date:
    start = _period_start(d, interval)
    if interval == TimeSeriesInterval.DAY:
        return start - timedelta(days=1)
    if interval == TimeSeriesInterval.WEEK:
        return start - timedelta(weeks=1)
    if interval == TimeSeriesInterval.MONTH:
        if start.month == 1:
            return date(start.year - 1, 12, 1)
        return date(start.year, start.month - 1, 1)
    if interval == TimeSeriesInterval.YEAR:
        return date(start.year - 1, 1, 1)
    return start


def _format_period(d: date, interval: TimeSeriesInterval) -> str:
    if interval == TimeSeriesInterval.DAY:
        return d.isoformat()
    if interval == TimeSeriesInterval.WEEK:
        return f"{d.isocalendar().year}-W{d.isocalendar().week:02d}"
    if interval == TimeSeriesInterval.MONTH:
        return d.strftime("%Y-%m")
    if interval == TimeSeriesInterval.YEAR:
        return str(d.year)
    return d.isoformat()


def _infer_grain(source_points: list[_SourcePoint]) -> TimeSeriesInterval | None:
    counts: dict[TimeSeriesInterval, int] = {}
    for sp in source_points:
        parsed = _parse_iso_period(sp.label)
        if parsed:
            counts[parsed.grain] = counts.get(parsed.grain, 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.get)  # type: ignore[arg-type]


def _infer_aggregation(
    value_column: str | None,
    metric_name: str,
    values: list[float],
) -> tuple[str, bool, str | None]:
    """Infer (aggregation, is_rate_or_ratio, value_format)."""
    col = (value_column or "").lower()
    name = metric_name.lower()
    if any(t in col for t in ("sum(", "total", "count(", "#")) or col.startswith("sum"):
        return ("sum", False, None)
    if any(t in col for t in ("avg(", "average(", "mean(")) or col.startswith("avg"):
        return ("avg", False, None)
    if any(t in col for t in ("min(", "max(")) or col.startswith("min") or col.startswith("max"):
        if col.startswith("min"):
            return ("min", False, None)
        return ("max", False, None)
    if any(t in name for t in ("margin", "rate", "ratio", "pct", "percent", "%", "avg")):
        value_format = "percent" if any(t in name for t in ("pct", "percent", "%", "margin")) else None
        return ("avg", True, value_format)
    # Heuristic on magnitude: values strictly between 0 and 1 often are ratios.
    if values:
        mx = max(abs(v) for v in values if v is not None)
        if 0 < mx < 1:
            return ("avg", True, "percent")
    return ("sum", False, None)


def _aggregate_values(values: list[float], aggregation: str) -> float:
    if not values:
        return 0.0
    if aggregation == "avg":
        return mean(values)
    if aggregation == "min":
        return min(values)
    if aggregation == "max":
        return max(values)
    return sum(values)


def _range_window(
    range_value: TimeSeriesRange,
    as_of: date,
) -> tuple[date, date, list[str]]:
    """Return (range_start, range_end, notes). Range end is inclusive."""
    notes: list[str] = []
    end = as_of
    if range_value == TimeSeriesRange.DAYS_7:
        start = as_of - timedelta(days=6)
    elif range_value == TimeSeriesRange.DAYS_30:
        start = as_of - timedelta(days=29)
    elif range_value == TimeSeriesRange.DAYS_90:
        start = as_of - timedelta(days=89)
    elif range_value == TimeSeriesRange.YEAR_1:
        try:
            start = date(as_of.year - 1, as_of.month, as_of.day) + timedelta(days=1)
        except ValueError:
            # Feb 29 -> Mar 1
            start = date(as_of.year - 1, as_of.month, as_of.day - 1) + timedelta(days=1)
        notes.append("1Y range is inclusive of the same date one year prior through today.")
    elif range_value == TimeSeriesRange.YEARS_2:
        try:
            start = date(as_of.year - 2, as_of.month, as_of.day) + timedelta(days=1)
        except ValueError:
            start = date(as_of.year - 2, as_of.month, as_of.day - 1) + timedelta(days=1)
        notes.append("2Y range is inclusive of the same date two years prior through today.")
    else:
        start = as_of - timedelta(days=29)
    return start, end, notes


def _extract_source_points(card: dict[str, Any]) -> list[_SourcePoint]:
    """Parse the card's chart data into (date, value, label) source points."""
    chart = card.get("chart") or {}
    data = chart.get("data") or {}
    roles = chart.get("roles") or {}
    series = data.get("series")
    rows = data.get("rows")
    out: list[_SourcePoint] = []

    if rows:
        x_col = roles.get("x") or card.get("labelColumn")
        y_col = roles.get("y") or roles.get("value") or card.get("valueColumn")
        if not x_col or not y_col:
            return out
        for row in rows:
            if not isinstance(row, dict):
                continue
            raw = row.get(x_col)
            parsed = _parse_iso_period(raw)
            if parsed is None:
                continue
            value = _to_float(row.get(y_col))
            out.append(_SourcePoint(parsed.date, value, parsed.raw))
    elif series:
        for item in series:
            if not isinstance(item, dict):
                continue
            raw = item.get("label")
            parsed = _parse_iso_period(raw)
            if parsed is None:
                continue
            value = _to_float(item.get("value"))
            value2 = _to_float(item.get("value2")) if "value2" in item else None
            out.append(_SourcePoint(parsed.date, value, parsed.raw, value2))
    return out


def _bucket_points(
    source_points: list[_SourcePoint],
    interval: TimeSeriesInterval,
    aggregation: str,
    as_of: date,
) -> dict[date, tuple[float | None, bool]]:
    """Bucket source points into the target interval. Returns bucket -> (value, partial)."""
    buckets: dict[date, list[float]] = {}
    for sp in source_points:
        if sp.value is None:
            continue
        bucket = _period_start(sp.date, interval)
        buckets.setdefault(bucket, []).append(sp.value)

    result: dict[date, tuple[float | None, bool]] = {}
    for bucket, values in sorted(buckets.items()):
        aggregated = _aggregate_values(values, aggregation)
        end = _period_end(bucket, interval)
        partial = as_of is not None and end > as_of
        result[bucket] = (aggregated, partial)
    return result


def _compare_periods(
    buckets: dict[date, tuple[float | None, bool]],
    interval: TimeSeriesInterval,
    is_rate_or_ratio: bool,
) -> list[tuple[date, float | None, float | None, float | None, bool, str, list[str]]]:
    """For each bucket, compute the previous-bucket comparison.

    Returns list of (bucket, current, previous, percent_ratio, partial, status, warnings).
    """
    out: list[tuple[date, float | None, float | None, float | None, bool, str, list[str]]] = []
    sorted_buckets = sorted(buckets.keys())
    for bucket in sorted_buckets:
        current, partial = buckets[bucket]
        warnings: list[str] = []
        prev_bucket = _previous_period_start(bucket, interval)
        previous = buckets.get(prev_bucket)
        status = "valid"
        ratio: float | None = None
        if current is None:
            status = "missing_current"
            out.append((bucket, None, previous[0] if previous else None, None, partial, status, warnings))
            continue
        if previous is None or previous[0] is None:
            status = "missing_previous"
            out.append((bucket, current, previous[0] if previous else None, None, partial, status, warnings))
            continue
        previous_value = previous[0]
        assert previous_value is not None
        if abs(Decimal(str(previous_value))) < _ZERO_TOLERANCE:
            status = "zero_baseline"
            warnings.append(
                f"Previous period ({_format_period(prev_bucket, interval)}) value is zero; "
                "percent change is undefined."
            )
        elif partial and is_rate_or_ratio:
            status = "partial_period"
            warnings.append(
                "Current period is incomplete and the metric is a rate or ratio; "
                "percent change is not shown to avoid comparing partial and full periods."
            )
        else:
            ratio = round(((current - previous_value) / previous_value), 6)
            if previous_value < 0:
                warnings.append(
                    "Previous-period value is negative; the percent-change sign follows "
                    "the algebraic formula, so a larger negative denominator can produce "
                    "a result that looks counter-intuitive."
                )
            if partial:
                warnings.append(
                    "Current period is incomplete; compare with the previous full period "
                    "as an early read only."
                )
        out.append((bucket, current, previous_value, ratio, partial, status, warnings))
    return out


def _percent_label(ratio: float | None) -> str | None:
    if ratio is None:
        return None
    return f"{(ratio * 100):+.1f}%"


def _supported_intervals(source_grain: TimeSeriesInterval) -> list[str]:
    order = [TimeSeriesInterval.DAY, TimeSeriesInterval.WEEK, TimeSeriesInterval.MONTH, TimeSeriesInterval.YEAR]
    idx = order.index(source_grain)
    return [i.value for i in order[idx:]]


def _interval_coarser_or_equal(
    source_grain: TimeSeriesInterval,
    target: TimeSeriesInterval,
) -> bool:
    order = {TimeSeriesInterval.DAY: 0, TimeSeriesInterval.WEEK: 1, TimeSeriesInterval.MONTH: 2, TimeSeriesInterval.YEAR: 3}
    return order[target] >= order[source_grain]


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
