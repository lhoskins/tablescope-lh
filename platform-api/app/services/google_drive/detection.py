"""Detect rectangular tables inside a Google Sheet for Workstream D.

Uses the live Sheet's grid dimensions, fetches the candidate range with
UNFORMATTED_VALUE, and returns a proposed ``SpreadsheetTableMapping`` shape.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from app.services.file_sources.classify import _classify
from app.services.google_drive.client import GoogleDriveClient, GoogleDriveError
from app.services.teiid_registration_service.naming import sanitize_identifier

logger = logging.getLogger(__name__)


def _column_letter(index: int) -> str:
    """Convert 1-indexed column number to A1 notation letter(s)."""
    letters = []
    while index > 0:
        index, rem = divmod(index - 1, 26)
        letters.append(chr(65 + rem))
    return "".join(reversed(letters))


def _quote_sheet_name(title: str) -> str:
    """Quote a sheet title for A1 notation; escape embedded single quotes."""
    return f"'{title.replace(chr(39), chr(39) * 2)}'"


def _is_non_empty(cell: Any) -> bool:
    return cell is not None and str(cell).strip() != ""


def _teiid_type_for(header: str, classification: str, sample_values: list[Any]) -> str:
    """Map a local classification to a Teiid DDL type."""
    if classification == "date":
        for v in sample_values:
            if _is_non_empty(v) and ":" in str(v):
                return "timestamp"
        return "date"
    if classification in ("number", "currency"):
        return "double"
    return "string"


def _detect_used_range(values: list[list[Any]]) -> tuple[int, int, int, int, list[str], list[list[Any]]]:
    """Return first_row, last_row, first_col, last_col, headers, data_rows.

    Indices are 0-based.  The first non-empty row is treated as the header.
    """
    if not values:
        raise GoogleDriveError("Sheet appears to be empty.")

    first_row = None
    last_row = 0
    first_col = None
    last_col = 0

    for r_idx, row in enumerate(values):
        row_has_value = False
        for c_idx, cell in enumerate(row):
            if not _is_non_empty(cell):
                continue
            row_has_value = True
            if first_row is None:
                first_row = r_idx
            if first_col is None or c_idx < first_col:
                first_col = c_idx
            if c_idx > last_col:
                last_col = c_idx
        if row_has_value:
            last_row = r_idx

    if first_row is None or first_col is None:
        raise GoogleDriveError("Sheet appears to be empty.")

    headers = [
        values[first_row][c] if c < len(values[first_row]) and _is_non_empty(values[first_row][c]) else f"Column_{c + 1}"
        for c in range(first_col, last_col + 1)
    ]
    data_start = first_row + 1
    data_rows = [
        row[first_col : last_col + 1]
        for row in values[data_start : last_row + 1]
    ]
    return first_row, last_row, first_col, last_col, headers, data_rows


async def detect_google_sheet_tables(
    client: GoogleDriveClient,
    file_id: str,
    sheet_name: str | None = None,
    max_rows: int = 1000,
) -> dict[str, Any]:
    """Return a single-table fallback proposal for the requested sheet.

    The result is a plain dict; the caller persists ``SpreadsheetTableMapping``
    and ``SpreadsheetColumnMapping`` rows.
    """
    meta = await client.get_file_metadata(file_id)
    file_name = meta.get("name") or file_id

    tabs = await client.list_sheet_tabs(file_id)
    if not tabs:
        raise GoogleDriveError("No sheets/tabs found in this spreadsheet.")

    if sheet_name:
        tab = next((t for t in tabs if t.get("title") == sheet_name), None)
        if tab is None:
            raise GoogleDriveError(f"Sheet '{sheet_name}' not found.")
    else:
        tab = tabs[0]

    title = tab.get("title") or "Sheet1"
    row_count = tab.get("rowCount") or max_rows
    col_count = tab.get("columnCount") or 26

    last_row = min(row_count, max_rows)
    last_col = min(col_count, 702)  # ZZ is the largest column we request

    start = "A1"
    end = f"{_column_letter(last_col)}{last_row}"
    range_a1 = f"{_quote_sheet_name(title)}!{start}:{end}"

    values = await client.get_range_values(file_id, range_a1)
    first_row, last_row, first_col, last_col, headers, data_rows = _detect_used_range(values)

    columns = []
    seen_relational_names: dict[str, int] = {}
    for offset, header in enumerate(headers):
        abs_col = first_col + offset
        sample = [
            row[offset] if offset < len(row) else None
            for row in data_rows
        ]
        classification = _classify(header or "", [str(v) for v in sample])
        teiid_type = _teiid_type_for(header or "", classification, sample)
        base_rel_name = sanitize_identifier(header or f"Column_{abs_col + 1}")
        count = seen_relational_names.get(base_rel_name, 0) + 1
        seen_relational_names[base_rel_name] = count
        relational_name = base_rel_name if count == 1 else f"{base_rel_name}_{count}"
        columns.append(
            {
                "ordinal": abs_col,
                "source_label": header or f"Column_{abs_col + 1}",
                "physical_column_ref": _column_letter(abs_col + 1),
                "relational_name": relational_name,
                "teiid_type": teiid_type,
                "classification": classification,
            }
        )

    header_row_index = first_row
    data_start_row_index = first_row + 1
    end_a1 = f"{_column_letter(last_col + 1)}{last_row + 1}"
    final_range_a1 = f"{_quote_sheet_name(title)}!{_column_letter(first_col + 1)}{first_row + 1}:{end_a1}"

    fingerprint = hashlib.sha256(json.dumps(headers, sort_keys=True).encode("utf-8")).hexdigest()

    return {
        "file_name": file_name,
        "sheet_name": title,
        "table_name": title,
        "range_a1": final_range_a1,
        "header_row_index": header_row_index,
        "data_start_row_index": data_start_row_index,
        "anchor_fingerprint": fingerprint,
        "detection_method": "single_table_fallback",
        "columns": columns,
    }
