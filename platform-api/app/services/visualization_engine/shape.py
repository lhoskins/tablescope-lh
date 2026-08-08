from __future__ import annotations

import re
from typing import Any

from .types import _ColumnShape, _Shape

# ── Shape detection (lightweight, dependency-free) ───────────────────────────
# The engine derives just enough shape to decide a chart. When the caller
# already has the M1 statistical profiler output, it can pass it via
# ``profile=`` and we reuse its column kinds; otherwise we classify here so a
# pure chart decision never pays for scipy/normality computation.

_PERIOD_LABEL_RE = re.compile(
    r"(?i)^\s*("
    r"(?:19|20|21)\d{2}"  # 1900-2199 years
    r"|(?:19|20|21)\d{2}[-/]\d{1,2}([-/]\d{1,2})?"  # 2026-01, 2026/01/15
    r"|q[1-4][\s-]?\d{2,4}"  # Q1 2026
    r"|(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?[\s-]?\d{0,4}"
    r"|(week|wk|day)\s?\d+"
    r")\s*$"
)
_PERIOD_COL_RE = re.compile(
    r"(?i)\b(period|month|year|quarter|week|date|day|fiscal|time)\b"
)

#: Above this many distinct categories (or when labels are id-like) a vertical
#: bar's x-axis ticks overlap, so the engine flips it to a horizontal bar whose
#: category labels stack readably down the y-axis.
_HORIZONTAL_BAR_THRESHOLD = 5
#: A bar with more categories than this is ranked by the measure and capped to
#: the top N — dozens of bars are unreadable and bury the story; the surface
#: still shows the full result in its data table beneath the chart.
_BAR_RANK_CAP = 12


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        s = value.strip().replace(",", "").replace("$", "").replace("%", "")
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _rows_as_dicts(columns: list[str], rows: list[Any]) -> list[dict[str, Any]]:
    if rows and isinstance(rows[0], dict):
        return list(rows)
    return [dict(zip(columns, r, strict=False)) for r in rows]


def _column_values(rows: list[dict[str, Any]], col: str, limit: int = 50) -> list[Any]:
    out: list[Any] = []
    for r in rows[:limit]:
        v = r.get(col)
        if v is not None and v != "":
            out.append(v)
    return out


def _classify_column(
    name: str, values: list[Any], profile_kind: str | None
) -> _ColumnShape:
    non_null = values
    if not non_null:
        return _ColumnShape(name, "empty", 0, False)
    cardinality = len({str(v) for v in non_null})
    numeric_hits = sum(1 for v in non_null if _to_float(v) is not None)
    numeric_rate = numeric_hits / len(non_null)

    period_col = bool(_PERIOD_COL_RE.search(name))
    str_vals = [str(v) for v in non_null]
    period_vals = (
        len(str_vals) >= 3
        and sum(1 for v in str_vals if _PERIOD_LABEL_RE.match(v))
        >= max(3, int(len(str_vals) * 0.6))
    )
    period_like = period_col or period_vals

    # Numeric years (2020, 2021, ...) read as a time dimension, not a measure.
    if numeric_rate >= 0.9 and period_like:
        return _ColumnShape(name, "period", cardinality, True)

    if profile_kind in ("numeric", "binary", "datetime", "categorical"):
        kind = "period" if (profile_kind == "datetime" or period_like) else profile_kind
        return _ColumnShape(name, kind, cardinality, period_like)

    if numeric_rate >= 0.9:
        uniq_numeric = len({_to_float(v) for v in non_null if _to_float(v) is not None})
        kind = "binary" if uniq_numeric <= 2 else "numeric"
        return _ColumnShape(name, kind, cardinality, period_like)
    if period_like:
        return _ColumnShape(name, "period", cardinality, True)
    if cardinality <= max(2, int(0.6 * len(non_null))):
        return _ColumnShape(name, "categorical", cardinality, False)
    return _ColumnShape(name, "text", cardinality, False)


def derive_shape(
    columns: list[str],
    rows: list[Any],
    profile: dict[str, Any] | None = None,
) -> _Shape:
    """Classify columns into measures / dimensions / time columns.

    When ``profile`` (the M1 data-profiler output) is provided we honour its
    column ``kind`` classification, so the Method Engine and Visualization Engine
    agree on the shape of the same result set.
    """
    dict_rows = _rows_as_dicts(columns, rows)
    profile_cols = (profile or {}).get("columns", {}) if profile else {}
    shapes: list[_ColumnShape] = []
    for col in columns:
        pk = None
        if col in profile_cols and isinstance(profile_cols[col], dict):
            pk = profile_cols[col].get("kind")
        shapes.append(_classify_column(col, _column_values(dict_rows, col), pk))

    measures = [c.name for c in shapes if c.kind in ("numeric", "binary")]
    time_columns = [c.name for c in shapes if c.kind == "period"]
    dimensions = [
        c.name for c in shapes if c.kind in ("categorical", "text", "period")
    ]
    return _Shape(
        row_count=len(dict_rows),
        columns=shapes,
        measures=measures,
        dimensions=dimensions,
        time_columns=time_columns,
    )



# ── Shape helpers ────────────────────────────────────────────────────────────

def _primary_dimension(shape: _Shape) -> str | None:
    """Pick the best label column: prefer a time column, then a categorical."""
    if shape.time_columns:
        return shape.time_columns[0]
    for c in shape.columns:
        if c.kind in ("categorical", "text"):
            return c.name
    return None


def _is_period_dimension(shape: _Shape, col: str) -> bool:
    return any(c.name == col and c.period_like for c in shape.columns)


def _dimension_cardinality(shape: _Shape, col: str | None) -> int:
    if col is None:
        return 0
    for c in shape.columns:
        if c.name == col:
            return c.cardinality
    return 0


def _cardinality(shape: _Shape, col: str) -> int:
    """Return the stored cardinality for a known column."""
    for c in shape.columns:
        if c.name == col:
            return c.cardinality
    return 0


def _has_negative(rows: list[dict[str, Any]], col: str) -> bool:
    for r in rows:
        v = _to_float(r.get(col))
        if v is not None and v < 0:
            return True
    return False


def _has_ohlc_roles(roles: dict[str, Any]) -> bool:
    return all(roles.get(k) for k in ("open", "high", "low", "close"))


def _looks_hierarchical(rows: list[dict[str, Any]], dims: list[str]) -> bool:
    """True when the first two dimensions look like a parent/child hierarchy."""
    if len(dims) < 2:
        return False
    parent_col, child_col = dims[0], dims[1]
    parent_for_child: dict[str, str] = {}
    parent_counts: dict[str, int] = {}
    for r in rows:
        parent = str(r.get(parent_col, ""))
        child = str(r.get(child_col, ""))
        if not parent or not child:
            continue
        if child in parent_for_child and parent_for_child[child] != parent:
            return False
        parent_for_child[child] = parent
        parent_counts[parent] = parent_counts.get(parent, 0) + 1
    # Need multiple parents and at least one parent with multiple children.
    return len(parent_counts) >= 2 and any(c > 1 for c in parent_counts.values())
