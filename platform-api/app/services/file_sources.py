"""Helpers for uploaded-file data sources.

* ``compute_view_name`` mirrors the Teiid import servlet's naming convention so
  a filename maps to the same VDB view name used by the query builder.
* ``detect_column_types`` inspects a sample of an uploaded file and classifies
  each column as ``date``, ``currency``, ``number`` or ``string`` so the UI can
  format values (item 6) and so the type hints can later be pushed into the VDB.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_CURRENCY_NAME_HINTS = (
    "amount",
    "price",
    "cost",
    "revenue",
    "total",
    "balance",
    "salary",
    "fee",
    "payment",
    "charge",
    "subtotal",
    "tax",
    "usd",
    "dollar",
)
_CURRENCY_CHARS = re.compile(r"^[\$\u20ac\u00a3\u00a5]")
_DATE_NAME_HINTS = ("date", "_dt", "day", "month", "year", "timestamp", "time")


def compute_view_name(filename: str) -> str:
    """Return the VDB view name the servlet assigns to ``filename``."""
    if "." in filename:
        base, ext = filename.rsplit(".", 1)
        base_name = base.replace(" ", "_")
        extension = ext.upper()
        return f"{base_name}_{extension}" if extension else base_name
    return filename.replace(" ", "_")


def _clean_number(value: str) -> str:
    """Strip currency symbols, thousands separators and whitespace."""
    v = value.strip()
    v = re.sub(r"[\$\u20ac\u00a3\u00a5,]", "", v)
    v = v.replace("(", "-").replace(")", "")
    return v.strip()


def _is_number(value: str) -> bool:
    v = _clean_number(value)
    if v in ("", "-", "."):
        return False
    try:
        float(v)
        return True
    except ValueError:
        return False


_DATE_PATTERNS = (
    re.compile(r"^\d{4}-\d{1,2}-\d{1,2}([ T]\d{1,2}:\d{2}(:\d{2})?)?$"),
    re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}([ T]\d{1,2}:\d{2}(:\d{2})?)?$"),
    re.compile(r"^\d{1,2}-\d{1,2}-\d{2,4}$"),
    re.compile(r"^\d{1,2}\.\d{1,2}\.\d{2,4}$"),
)


def _is_date(value: str) -> bool:
    v = value.strip()
    if not v or _is_number(v):
        return False
    return any(p.match(v) for p in _DATE_PATTERNS)


def _classify(name: str, values: list[str]) -> str:
    non_empty = [v for v in values if v is not None and str(v).strip() != ""]
    if not non_empty:
        return "string"
    lname = name.lower()

    date_hits = sum(1 for v in non_empty if _is_date(str(v)))
    if date_hits / len(non_empty) >= 0.8:
        return "date"

    num_hits = sum(1 for v in non_empty if _is_number(str(v)))
    if num_hits / len(non_empty) >= 0.8:
        has_currency_char = any(_CURRENCY_CHARS.match(str(v).strip()) for v in non_empty)
        name_is_currency = any(h in lname for h in _CURRENCY_NAME_HINTS)
        if has_currency_char or name_is_currency:
            return "currency"
        return "number"

    # Name hint fall-backs when sampled data is sparse/ambiguous.
    if any(h in lname for h in _DATE_NAME_HINTS):
        return "date"
    return "string"


def _read_csv_sample(content: bytes, max_rows: int = 200) -> tuple[list[str], list[list[str]]]:
    text = content.decode("utf-8-sig", errors="replace")
    sample = text[:8192]
    delimiter = ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = "\t" if "\t" in sample.splitlines()[0] else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = list(reader)
    if not rows:
        return [], []
    header = [h.strip() for h in rows[0]]
    data = rows[1 : 1 + max_rows]
    return header, data


def _read_xlsx_sample(content: bytes, max_rows: int = 200) -> tuple[list[str], list[list[str]]]:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    try:
        header_row = next(rows_iter)
    except StopIteration:
        return [], []
    header = [str(h).strip() if h is not None else "" for h in header_row]
    data: list[list[str]] = []
    for i, r in enumerate(rows_iter):
        if i >= max_rows:
            break
        data.append([("" if c is None else str(c)) for c in r])
    wb.close()
    return header, data


def detect_column_types(content: bytes, filename: str) -> list[dict[str, Any]]:
    """Detect a formatting type for each column of an uploaded file.

    Returns a list of ``{"name", "type"}`` where ``type`` is one of
    ``date | currency | number | string``.  Never raises — on any parse error
    it returns an empty list so upload is unaffected.
    """
    try:
        lower = filename.lower()
        if lower.endswith((".xlsx", ".xlsm", ".xls")):
            header, data = _read_xlsx_sample(content)
        else:
            header, data = _read_csv_sample(content)
    except Exception as exc:  # detection is best-effort
        logger.warning("Column type detection failed for %s: %s", filename, exc)
        return []

    if not header:
        return []

    result: list[dict[str, Any]] = []
    for idx, name in enumerate(header):
        col_values = [row[idx] for row in data if idx < len(row)]
        col_type = _classify(name, col_values)
        # The view normalizes header spaces to underscores; expose both so the
        # grid can match either the raw or normalized field name.
        result.append(
            {
                "name": name,
                "field": name.replace(" ", "_"),
                "type": col_type,
            }
        )
    return result
