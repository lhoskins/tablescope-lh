"""VDB XML editing helpers for live remote file sources.

These helpers mutate the per-tenant VDB XML so URL/SMB imports read the remote
file at query time through the RemoteCSVSourceModel instead of being staged as
local files.
"""

from __future__ import annotations

import re

from app.services.file_sources.sanitize import sanitize_column_name


def _quote_sql_str(value: str) -> str:
    return value.replace("'", "''")


def _sanitize_header(name: str) -> str:
    return sanitize_column_name(name)


def ensure_remote_models(vdb_xml: str) -> str:
    """Ensure the VDB has the RemoteCSVSourceModel physical model."""
    if 'name="RemoteCSVSourceModel"' in vdb_xml:
        return vdb_xml

    remote_model = """
  <!-- Hidden model for live remote CSV/Text files -->
  <model name="RemoteCSVSourceModel" type="PHYSICAL" visible="false">
    <source name="remote-text-connector" translator-name="file" connection-jndi-name="java:/remote-file-ds"/>
    <metadata type="DDL">
      <![CDATA[
CREATE FOREIGN PROCEDURE getTextFiles (
  IN pathAndExt string(4000) NOT NULL
) RETURNS
  TABLE (
    file clob,
    filePath string(4000),
    lastModified timestamp,
    created timestamp,
    size integer
  ) OPTIONS(UPDATECOUNT '1');
]]>
    </metadata>
  </model>
"""
    # Insert immediately after the CSVSourceModel model if possible.
    match = re.search(
        r"(<model name=\"CSVSourceModel\".*?</model>)", vdb_xml, re.DOTALL
    )
    if match:
        end = match.end()
        return vdb_xml[:end] + remote_model + vdb_xml[end:]
    # Fall back to before the closing </vdb> tag.
    return re.sub(r"(</vdb>\s*)$", remote_model + r"\1", vdb_xml)


def _view_marker() -> str:
    return "-- Place new View above"


def remove_remote_view(vdb_xml: str, view_name: str) -> str:
    """Remove an existing remote view with the same name from the MyCompany model."""
    # Match from CREATE VIEW through the terminating semicolon.  The DDL column
    # list contains parentheses inside OPTIONS(...) so a balanced-paren regex is
    # not safe; a non-greedy match to the next semicolon works because Teiid DDL
    # emitted here never contains an embedded semicolon.
    pattern = re.compile(
        rf'CREATE VIEW\s+"{re.escape(view_name)}"\s+.*?;',
        re.DOTALL,
    )
    return pattern.sub("", vdb_xml)


def build_remote_csv_view_ddl(
    view_name: str,
    headers: list[str],
    data_source_id: int,
    delimiter: str = ",",
) -> str:
    """Return a CREATE VIEW DDL string for a live remote CSV/Text source."""
    sanitized: list[tuple[str, str]] = []
    for name in headers:
        clean = _sanitize_header(name)
        # Deduplicate while preserving order.
        counter = 1
        base = clean
        while clean in [c for _, c in sanitized]:
            clean = f"{base}_{counter}"
            counter += 1
        sanitized.append((name, clean))

    if not sanitized:
        sanitized = [("value", "value")]

    def_view_cols = ",\n".join(
        f'  {clean} string(4000) OPTIONS(NAMEINSOURCE \'{_quote_sql_str(name)}\', UPDATABLE \'FALSE\')'
        for name, clean in sanitized
    )
    texttable_cols = ", ".join(f"{clean} string" for _, clean in sanitized)
    select_cols = ",\n".join(f"A.{clean}" for _, clean in sanitized)

    escaped_delim = _quote_sql_str(delimiter)

    return (
        f'CREATE VIEW "{view_name}" (\n'
        f"{def_view_cols}\n"
        f") AS\n"
        f"SELECT\n"
        f"{select_cols}\n"
        f"FROM\n"
        f"(EXEC RemoteCSVSourceModel.getTextFiles('remote://ds:{data_source_id}')) AS f,\n"
        f"TEXTTABLE(f.file COLUMNS {texttable_cols} DELIMITER '{escaped_delim}' HEADER) AS A;"
    )


def add_remote_csv_view(
    vdb_xml: str,
    view_name: str,
    headers: list[str],
    data_source_id: int,
    delimiter: str = ",",
) -> str:
    """Add (or replace) a live remote CSV view in the VDB metadata."""
    vdb_xml = ensure_remote_models(vdb_xml)
    vdb_xml = remove_remote_view(vdb_xml, view_name)
    marker = _view_marker()
    if marker not in vdb_xml:
        raise ValueError("VDB MyCompany metadata marker not found")
    ddl = build_remote_csv_view_ddl(view_name, headers, data_source_id, delimiter)
    return vdb_xml.replace(marker, ddl + "\n" + marker)
