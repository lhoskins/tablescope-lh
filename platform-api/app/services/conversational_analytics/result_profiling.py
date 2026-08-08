
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .intent_classification import _MAX_PREVIEW_BYTES, _MAX_PREVIEW_ROWS


def _answer_text(columns: list[str], rows: list[dict[str, Any]]) -> str:
    """Short deterministic answer for an executed data turn.

    States the single scalar for KPI-style results, otherwise the row count.
    The chart + table carry the detail; raw model prose never reaches chat.
    """
    if not rows:
        return "The query ran but returned no rows."
    if len(rows) == 1 and len(columns) == 1:
        return f"{columns[0]}: {rows[0].get(columns[0])}"
    return f"Here are the results ({len(rows)} rows)."


def _sql_fingerprint(sql: str | None) -> str | None:
    if not sql:
        return None
    normalized = " ".join(sql.lower().split())
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def _bound_result(rows: list[dict[str, Any]], max_rows: int = _MAX_PREVIEW_ROWS, max_bytes: int = _MAX_PREVIEW_BYTES) -> tuple[list[dict[str, Any]], bool]:
    """Trim preview rows/columns to bounded limits."""
    if not rows:
        return [], False
    bounded = rows[:max_rows]
    total = json.dumps(bounded, default=str)
    while len(total.encode()) > max_bytes and len(bounded) > 1:
        bounded = bounded[: len(bounded) // 2]
        total = json.dumps(bounded, default=str)
    truncated = len(rows) > len(bounded)
    return bounded, truncated


def _profile_result(columns: list[str], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Lightweight result profiler for storage and chart recommendation."""
    if not columns or not rows:
        return {"columns": columns or [], "rowCount": 0}
    sample = rows[0]
    numeric: list[str] = []
    categorical: list[str] = []
    datetime_cols: list[str] = []
    for col in columns:
        val = sample.get(col)
        if isinstance(val, int | float):
            numeric.append(col)
        elif isinstance(val, str) and re.match(r"^\d{4}-\d{2}-\d{2}", val):
            datetime_cols.append(col)
        else:
            categorical.append(col)
    return {
        "columns": columns,
        "rowCount": len(rows),
        "numericColumns": numeric,
        "categoricalColumns": categorical,
        "datetimeColumns": datetime_cols,
    }


def _to_float(value: Any) -> float | None:
    """Parse a scalar value to float, tolerating numeric strings."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        text = value.replace(",", "").strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _is_period_values(values: list[Any]) -> bool:
    """True when most non-null values look like sortable period labels."""
    non_null = [v for v in values if v is not None and v != ""]
    if not non_null:
        return False
    period_re = re.compile(r"^\s*(\d{4}|\d{4}[-/]\d{1,2}([-/]\d{1,2})?|q[1-4][\s-]?\d{2,4})\s*$", re.IGNORECASE)
    return sum(1 for v in non_null if period_re.match(str(v))) >= max(1, len(non_null) // 2)


def _column_data_profile(columns: list[str], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Classify each column as numeric, period, or categorical from its values."""
    profile: dict[str, Any] = {"numeric": [], "period": [], "categorical": []}
    for col in columns:
        values = [r.get(col) for r in rows]
        non_null = [v for v in values if v is not None and v != ""]
        if not non_null:
            profile["categorical"].append(col)
            continue
        numeric_count = sum(1 for v in non_null if _to_float(v) is not None)
        if numeric_count >= len(non_null) / 2:
            profile["numeric"].append(col)
        elif _is_period_values(non_null):
            profile["period"].append(col)
        else:
            profile["categorical"].append(col)
    return profile
