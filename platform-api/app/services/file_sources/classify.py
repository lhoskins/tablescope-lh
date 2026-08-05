
from __future__ import annotations

import logging
import re
from typing import Any

from .format_readers import _read_csv_sample, _read_xlsx_sample

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
