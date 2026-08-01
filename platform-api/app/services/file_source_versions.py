"""Schema comparison and staging helpers for data-source updates.

The drag-to-update / ``Update data source`` workflow stages an incoming file,
compares it against the active version and only then activates it. The pure
functions here own the comparison so both the preflight endpoint and the tests
share one definition of "is this change safe".
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Update modes the service supports today.
MODE_REPLACE = "replace"

STAGING_DIRNAME = ".staging"
ARCHIVE_DIRNAME = ".versions"


def checksum(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def staging_dir(uploads_dir: Path) -> Path:
    return uploads_dir / STAGING_DIRNAME


def archive_dir(uploads_dir: Path) -> Path:
    return uploads_dir / ARCHIVE_DIRNAME


def count_data_rows(content: bytes, filename: str) -> int | None:
    """Best-effort row count (excluding the header) for a tabular file."""
    lower = filename.lower()
    try:
        if lower.endswith((".xlsx", ".xlsm", ".xls")):
            import openpyxl

            wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
            ws = wb.active
            total = max((ws.max_row or 1) - 1, 0)
            wb.close()
            return total
        text = content.decode("utf-8-sig", errors="replace")
        reader = csv.reader(io.StringIO(text))
        total = sum(1 for _ in reader)
        return max(total - 1, 0)
    except Exception as exc:  # counting is advisory only
        logger.warning("Row count failed for %s: %s", filename, exc)
        return None


def _by_field(column_types: list[dict[str, Any]] | None) -> dict[str, str]:
    return {
        str(col.get("field") or col.get("name")): str(col.get("type") or "")
        for col in (column_types or [])
        if col.get("field") or col.get("name")
    }


def compare_schemas(
    existing: list[dict[str, Any]] | None,
    incoming: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Compare two detected schemas.

    Removals and type changes are blocking: a dependent query, dashboard or
    insight can be silently broken by either. Added columns are informational.
    """
    old = _by_field(existing)
    new = _by_field(incoming)
    removed = sorted(set(old) - set(new))
    added = sorted(set(new) - set(old))
    type_changed = [
        {"column": name, "from": old[name], "to": new[name]}
        for name in sorted(set(old) & set(new))
        if old[name] and new[name] and old[name] != new[name]
    ]
    blockers: list[str] = []
    if removed:
        blockers.append(
            "Replacement file is missing existing column(s): " + ", ".join(removed)
        )
    if type_changed:
        blockers.append(
            "Column type change(s) detected: "
            + ", ".join(f"{c['column']} ({c['from']} → {c['to']})" for c in type_changed)
        )
    return {
        "addedColumns": added,
        "removedColumns": removed,
        "typeChangedColumns": type_changed,
        "blockers": blockers,
        "compatible": not blockers,
    }
