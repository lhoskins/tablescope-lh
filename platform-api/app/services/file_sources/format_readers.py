
from __future__ import annotations

import csv
import io
from typing import Any

from .sanitize import sanitize_column_name


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
    """Serialize a list of record dicts to CSV bytes (union of keys as header).

    Column names are sanitized to be SQL-safe.
    """
    raw_columns: list[str] = []
    seen_raw: set[str] = set()
    for row in rows:
        for key in row.keys():
            if key not in seen_raw:
                seen_raw.add(key)
                raw_columns.append(key)
    # Map raw keys to sanitized column names
    col_map: dict[str, str] = {}
    seen_clean: dict[str, int] = {}
    columns: list[str] = []
    for raw in raw_columns:
        clean = sanitize_column_name(raw)
        if clean in seen_clean:
            seen_clean[clean] += 1
            clean = f"{clean}_{seen_clean[clean]}"
        else:
            seen_clean[clean] = 0
        col_map[raw] = clean
        columns.append(clean)
    if not columns:
        columns = ["value"]
        raw_columns = ["value"]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_flatten_value(row.get(raw, "")) for raw in raw_columns])
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
