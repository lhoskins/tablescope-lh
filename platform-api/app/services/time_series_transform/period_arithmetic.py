
from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta
from typing import Any

from .models import TimeSeriesInterval, _ParsedPeriod, _SourcePoint


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


def _next_period_start(d: date, interval: TimeSeriesInterval) -> date:
    start = _period_start(d, interval)
    if interval == TimeSeriesInterval.DAY:
        return start + timedelta(days=1)
    if interval == TimeSeriesInterval.WEEK:
        return start + timedelta(weeks=1)
    if interval == TimeSeriesInterval.MONTH:
        if start.month == 12:
            return date(start.year + 1, 1, 1)
        return date(start.year, start.month + 1, 1)
    if interval == TimeSeriesInterval.YEAR:
        return date(start.year + 1, 1, 1)
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
