"""File profiling service — extracts schema, sample rows, and quality stats.

Supports CSV, XLSX, and TXT files. Profiles are compact summaries sent to the
AI analysis service (never the full file).
"""

from __future__ import annotations

import csv
import io
import logging
import re
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

MAX_SAMPLE_ROWS = 50
MAX_DISTINCT_TRACK = 10_000
MAX_SAMPLE_VALUES = 5


def profile_uploaded_file(
    content: bytes,
    file_name: str,
    file_type: str | None = None,
    max_sample_rows: int = MAX_SAMPLE_ROWS,
) -> dict[str, Any]:
    """Profile an uploaded file and return a compact metadata summary.

    Returns a dict with keys: file_name, file_type, file_size_bytes,
    row_count, column_count, sheet_name, fields, sample_rows.
    """
    resolved_type = file_type or _detect_file_type(file_name)
    if resolved_type in ("xlsx", "xlsm", "xls"):
        return _profile_excel(content, file_name, resolved_type, max_sample_rows)
    return _profile_csv(content, file_name, resolved_type, max_sample_rows)


def _detect_file_type(file_name: str) -> str:
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    return ext or "csv"


def _profile_csv(
    content: bytes, file_name: str, file_type: str, max_sample_rows: int
) -> dict[str, Any]:
    """Profile a CSV/TXT file."""
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))

    try:
        headers = next(reader)
    except StopIteration:
        return _empty_profile(file_name, file_type, len(content))

    headers = [h.strip() for h in headers]
    col_count = len(headers)

    # Collect all rows for profiling (stream for large files)
    rows: list[list[str]] = []
    for row in reader:
        rows.append(row)

    row_count = len(rows)
    sample_rows = rows[:max_sample_rows]

    fields = _profile_fields(headers, rows, max_sample_rows)

    return {
        "file_name": file_name,
        "file_type": file_type,
        "file_size_bytes": len(content),
        "row_count": row_count,
        "column_count": col_count,
        "sheet_name": None,
        "fields": fields,
        "sample_rows": [dict(zip(headers, r, strict=False)) for r in sample_rows[:10]],
    }


def _profile_excel(
    content: bytes, file_name: str, file_type: str, max_sample_rows: int
) -> dict[str, Any]:
    """Profile an XLSX file using openpyxl."""
    try:
        import openpyxl
    except ImportError:
        logger.warning("openpyxl not installed — falling back to CSV profiling")
        return _profile_csv(content, file_name, file_type, max_sample_rows)

    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    if ws is None:
        return _empty_profile(file_name, file_type, len(content))

    sheet_name = ws.title

    rows_iter = ws.iter_rows(values_only=True)
    try:
        header_row = next(rows_iter)
    except StopIteration:
        return _empty_profile(file_name, file_type, len(content), sheet_name)

    headers = [str(h).strip() if h is not None else f"Column_{i}" for i, h in enumerate(header_row)]
    col_count = len(headers)

    rows: list[list[str]] = []
    for row_vals in rows_iter:
        rows.append([str(v) if v is not None else "" for v in row_vals])

    row_count = len(rows)
    fields = _profile_fields(headers, rows, max_sample_rows)

    wb.close()

    return {
        "file_name": file_name,
        "file_type": file_type,
        "file_size_bytes": len(content),
        "row_count": row_count,
        "column_count": col_count,
        "sheet_name": sheet_name,
        "fields": fields,
        "sample_rows": [dict(zip(headers, r, strict=False)) for r in rows[:10]],
    }


def _profile_fields(
    headers: list[str],
    rows: list[list[str]],
    max_sample_rows: int,
) -> list[dict[str, Any]]:
    """Profile each column/field."""
    fields: list[dict[str, Any]] = []

    for col_idx, header in enumerate(headers):
        values = [
            row[col_idx] if col_idx < len(row) else ""
            for row in rows
        ]

        non_empty = [v for v in values if v.strip()]
        null_count = len(values) - len(non_empty)
        null_percent = (null_count / len(values) * 100) if values else 0

        distinct_values = set()
        lengths: list[int] = []
        for v in non_empty:
            if len(distinct_values) < MAX_DISTINCT_TRACK:
                distinct_values.add(v)
            lengths.append(len(v))

        detected_type = _detect_column_type(non_empty)

        sample_vals = list(distinct_values)[:MAX_SAMPLE_VALUES]

        fields.append({
            "field_name": header,
            "detected_type": detected_type,
            "recommended_type": detected_type,
            "max_length": max(lengths) if lengths else 0,
            "min_length": min(lengths) if lengths else 0,
            "nullable": null_count > 0,
            "null_count": null_count,
            "null_percent": round(null_percent, 4),
            "distinct_count": len(distinct_values),
            "sample_values": sample_vals,
            "min_value": min(non_empty) if non_empty else None,
            "max_value": max(non_empty) if non_empty else None,
        })

    return fields


def _detect_column_type(values: list[str]) -> str:
    """Heuristic type detection for a column's values."""
    if not values:
        return "string"

    sample = values[:200]

    int_count = 0
    float_count = 0
    date_count = 0
    bool_count = 0

    for v in sample:
        v_strip = v.strip()
        if not v_strip:
            continue
        if v_strip.lower() in ("true", "false", "yes", "no", "1", "0"):
            bool_count += 1
        if _is_integer(v_strip):
            int_count += 1
        elif _is_float(v_strip):
            float_count += 1
        elif _is_date(v_strip):
            date_count += 1

    total = len(sample)
    threshold = 0.8

    if int_count / total >= threshold:
        return "integer"
    if (int_count + float_count) / total >= threshold:
        return "decimal"
    if date_count / total >= threshold:
        return "date"
    if bool_count / total >= threshold:
        return "boolean"
    return "string"


_INT_RE = re.compile(r"^-?\d{1,15}$")
_FLOAT_RE = re.compile(r"^-?\d{1,15}\.\d+$")
_CURRENCY_RE = re.compile(r"^\$?-?\d{1,15}([,.]\d+)*$")


def _is_integer(v: str) -> bool:
    return bool(_INT_RE.match(v.replace(",", "")))


def _is_float(v: str) -> bool:
    cleaned = v.replace(",", "").lstrip("$")
    return bool(_FLOAT_RE.match(cleaned))


def _is_date(v: str) -> bool:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S",
                "%m-%d-%Y", "%Y/%m/%d", "%d-%b-%Y", "%b %d, %Y"):
        try:
            datetime.strptime(v.strip(), fmt)
            return True
        except ValueError:
            continue
    return False


def _empty_profile(
    file_name: str, file_type: str, size: int, sheet_name: str | None = None
) -> dict[str, Any]:
    return {
        "file_name": file_name,
        "file_type": file_type,
        "file_size_bytes": size,
        "row_count": 0,
        "column_count": 0,
        "sheet_name": sheet_name,
        "fields": [],
        "sample_rows": [],
    }
