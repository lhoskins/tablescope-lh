
from __future__ import annotations

import csv
import io

from .format_readers import _json_to_rows, _rows_to_csv, _xml_to_rows
from .sanitize import (
    _LEADING_TRAILING_US,
    _MULTI_UNDERSCORES,
    _RESERVED_CHARS_RE,
    sanitize_csv_content,
    sanitize_excel_content,
    sanitize_filename,
    sanitize_xlsx_content,
)


def _csv_bytes_to_xlsx(content: bytes, extension: str = "xlsx") -> bytes:
    """Convert CSV/TSV bytes to a sanitized Excel workbook."""
    import openpyxl

    text = content.decode("utf-8-sig", errors="replace")
    sample = text[:8192]
    delimiter = ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = "\t" if "\t" in text.splitlines()[0] else ","
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in csv.reader(io.StringIO(text), delimiter=delimiter):
        ws.append(row)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# Formats that the Teiid servlet cannot import natively and must be flattened to CSV.
_FLATTENED_FORMATS = frozenset({"json", "xml", "xls"})


def physical_file_name(file_name: str, source_format: str | None) -> str:
    """Return the on-disk filename for a source given its display filename.

    Excel (.xlsx, .xlsm), CSV, TSV and TXT keep their extension. JSON, XML and
    legacy .xls are normalized to .csv for the Teiid import servlet.
    """
    ext = (source_format or "").lower()
    if not ext or ext in _FLATTENED_FORMATS:
        if "." in file_name:
            return file_name.rsplit(".", 1)[0] + ".csv"
        return file_name + ".csv"
    return file_name


def candidate_physical_names(file_name: str, source_format: str | None) -> list[str]:
    """Possible on-disk filenames for a source, newest/primary first."""
    base = sanitize_filename(file_name)
    ext = (source_format or "").lower()
    candidates = []
    if ext in {"xlsx", "xlsm"}:
        candidates.append(base)
        # Legacy rows may have been flattened to .csv before Excel preservation.
        if "." in base:
            candidates.append(f"{base.rsplit('.', 1)[0]}.csv")
        else:
            candidates.append(f"{base}.csv")
    elif ext in _FLATTENED_FORMATS:
        if "." in base:
            candidates.append(f"{base.rsplit('.', 1)[0]}.csv")
        else:
            candidates.append(f"{base}.csv")
    else:
        candidates.append(base)
    return candidates


def prepare_upload_content(file_name: str, content: bytes) -> tuple[str, bytes, str | None]:
    """Sanitize an upload and return ``(physical_filename, content, source_format)``.

    ``physical_filename`` is the name actually written to disk and sent to the
    Teiid servlet; ``source_format`` is the original extension for display.
    """
    original_format = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else None
    clean_name = sanitize_filename(file_name)
    ext = clean_name.rsplit(".", 1)[-1].lower() if "." in clean_name else ""

    if ext == "xls":
        # Legacy binary Excel is flattened to CSV.
        content = sanitize_xlsx_content(content)
        clean_name = clean_name.rsplit(".", 1)[0] + ".csv"
    elif ext in {"xlsx", "xlsm"}:
        content = sanitize_excel_content(content, ext)
    elif ext in {"csv", "tsv", "txt"}:
        content = sanitize_csv_content(content)
    elif ext in {"json", "xml"}:
        clean_name, content = convert_to_csv_if_needed(clean_name, content)
    # Unknown extension is passed through.
    return clean_name, content, original_format


def prepare_replacement_content(
    incoming_file_name: str,
    content: bytes,
    target_physical_name: str,
) -> bytes:
    """Convert/sanitize ``content`` so it can be written as ``target_physical_name``."""
    target_ext = target_physical_name.rsplit(".", 1)[-1].lower() if "." in target_physical_name else ""
    incoming_ext = (
        sanitize_filename(incoming_file_name).rsplit(".", 1)[-1].lower()
        if "." in incoming_file_name
        else ""
    )

    if target_ext == incoming_ext:
        if target_ext in {"xlsx", "xlsm"}:
            return sanitize_excel_content(content, target_ext)
        # CSV/TSV/TXT replacements are staged/activated as-is; the Teiid
        # servlet sanitizes headers and values on import.
        return content

    if target_ext in {"xlsx", "xlsm"}:
        if incoming_ext in {"xlsx", "xlsm", "xls"}:
            return sanitize_excel_content(content, target_ext)
        # CSV/TSV/TXT/JSON/XML -> xlsx
        if incoming_ext in {"json", "xml"}:
            _, csv_bytes = convert_to_csv_if_needed(f"data.{incoming_ext}", content)
        elif incoming_ext in {"csv", "tsv", "txt"}:
            csv_bytes = sanitize_csv_content(content)
        else:
            csv_bytes = content
        return _csv_bytes_to_xlsx(csv_bytes, target_ext)

    if target_ext == "csv":
        if incoming_ext in {"xlsx", "xlsm", "xls"}:
            return sanitize_xlsx_content(content)
        if incoming_ext in {"json", "xml"}:
            _, csv_bytes = convert_to_csv_if_needed(f"data.{incoming_ext}", content)
            return csv_bytes
        if incoming_ext in {"csv", "tsv", "txt"}:
            return sanitize_csv_content(content)
        return content

    return content


def compute_view_name(filename: str) -> str:
    """Return the VDB view name the servlet assigns to ``filename``.

    Applies the same sanitization used during upload so the view name is safe
    as a SQL identifier.
    """
    if "." in filename:
        base, ext = filename.rsplit(".", 1)
    else:
        base, ext = filename, ""
    base_name = _RESERVED_CHARS_RE.sub("_", base)
    base_name = base_name.replace(" ", "_")
    base_name = _MULTI_UNDERSCORES.sub("_", base_name)
    base_name = _LEADING_TRAILING_US.sub("", base_name)
    if not base_name:
        base_name = "file"
    extension = ext.upper() if ext else ""
    return f"{base_name}_{extension}" if extension else base_name


def display_source(
    physical_name: str, source_format: str | None
) -> tuple[str, str]:
    """Return ``(display_file_name, source_type)`` honoring the original upload.

    JSON/XML uploads are flattened to CSV, so the physical file on disk is
    ``foo.csv``. When ``source_format`` is recorded (e.g. ``"json"``) we present
    the original extension instead (``foo.json`` + type ``json``); otherwise we
    fall back to the on-disk extension.
    """
    ext = physical_name.rsplit(".", 1)[-1].lower() if "." in physical_name else ""
    if source_format:
        stem = (
            physical_name.rsplit(".", 1)[0]
            if "." in physical_name
            else physical_name
        )
        return f"{stem}.{source_format}", source_format
    return physical_name, (ext or "file")


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
