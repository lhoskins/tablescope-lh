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


def _flatten_value(value: Any) -> str:
    """Render a JSON/XML cell value as a flat string.

    Scalars become their string form; nested objects/arrays are serialized to
    compact JSON so the column still carries the data without breaking the
    tabular shape.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str | int | float):
        return str(value)
    import json as _json

    return _json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _rows_to_csv(rows: list[dict[str, Any]]) -> bytes:
    """Serialize a list of record dicts to CSV bytes (union of keys as header)."""
    columns: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                columns.append(key)
    if not columns:
        columns = ["value"]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_flatten_value(row.get(col, "")) for col in columns])
    return buf.getvalue().encode("utf-8")


def _json_to_rows(content: bytes) -> list[dict[str, Any]]:
    import json as _json

    data = _json.loads(content.decode("utf-8-sig"))
    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        # Common API wrappers: use the first list-of-objects value if present,
        # otherwise treat the object itself as a single row.
        nested = next(
            (v for v in data.values() if isinstance(v, list) and v and all(
                isinstance(i, dict) for i in v
            )),
            None,
        )
        records = nested if nested is not None else [data]
    else:
        records = [{"value": data}]
    rows: list[dict[str, Any]] = []
    for rec in records:
        if isinstance(rec, dict):
            rows.append(rec)
        else:
            rows.append({"value": rec})
    return rows


def _xml_to_rows(content: bytes) -> list[dict[str, Any]]:
    import xml.etree.ElementTree as ET

    root = ET.fromstring(content)

    def _local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1] if "}" in tag else tag

    def _element_to_row(el: ET.Element) -> dict[str, Any]:
        row: dict[str, Any] = {}
        for attr, val in el.attrib.items():
            row[_local(attr)] = val
        for child in el:
            key = _local(child.tag)
            if len(child) == 0:
                row[key] = (child.text or "").strip()
            else:
                row[key] = {
                    _local(gc.tag): (gc.text or "").strip() for gc in child
                }
        text = (el.text or "").strip()
        if text and not row:
            row["value"] = text
        return row

    children = list(root)
    # Find the dominant repeating child tag -> those become the rows.
    if children:
        from collections import Counter

        counts = Counter(_local(c.tag) for c in children)
        top_tag, top_n = counts.most_common(1)[0]
        if top_n > 1:
            return [_element_to_row(c) for c in children if _local(c.tag) == top_tag]
        # Single record: the root's children describe one row.
        return [_element_to_row(root)]
    return [_element_to_row(root)]


def convert_to_csv_if_needed(filename: str, content: bytes) -> tuple[str, bytes]:
    """Convert JSON/XML uploads to CSV so they ride the existing file pipeline.

    Returns ``(filename, content)`` unchanged for non-JSON/XML inputs. For
    ``.json``/``.xml`` the content is flattened to CSV and the filename's
    extension is rewritten to ``.csv`` so the Teiid import servlet (which only
    parses CSV/TXT/Excel) treats it as a normal tabular data source. Raises
    ``ValueError`` with a friendly message if the file can't be parsed.
    """
    lower = filename.lower()
    if lower.endswith(".json"):
        try:
            rows = _json_to_rows(content)
        except Exception as exc:
            raise ValueError(f"Could not parse JSON file: {exc}") from exc
    elif lower.endswith(".xml"):
        try:
            rows = _xml_to_rows(content)
        except Exception as exc:
            raise ValueError(f"Could not parse XML file: {exc}") from exc
    else:
        return filename, content

    csv_bytes = _rows_to_csv(rows)
    base = filename.rsplit(".", 1)[0]
    return f"{base}.csv", csv_bytes


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
