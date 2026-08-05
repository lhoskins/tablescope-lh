
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from statistics import mean
from typing import Any

from .models import _ZERO_TOLERANCE, TimeSeriesInterval, TimeSeriesRange, _SourcePoint
from .period_arithmetic import (
    _format_period,
    _parse_iso_period,
    _period_end,
    _period_start,
    _previous_period_start,
    _to_float,
)


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
