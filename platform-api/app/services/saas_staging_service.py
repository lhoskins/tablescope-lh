"""Local Postgres staging for SaaS objects.

SaaS objects are synced into typed staging tables in a dedicated ``saas_staging``
schema in the platform's own Postgres database.  Teiid then reads those tables
through the ordinary database-table pipeline, so synced HubSpot/Salesforce data
joins with files and databases with no special handling.

Every staging table gets a ``raw_json`` JSONB column holding the full source
payload so no data is lost even when only a few fields are projected to typed
columns.  Upserts key on the connector's id column.
"""

from __future__ import annotations

import json
import logging
import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.base import RAW_JSON_KEY, StagingColumn

logger = logging.getLogger(__name__)

STAGING_SCHEMA = "saas_staging"

# Identifiers we generate (table) or accept from SaaS metadata (columns) must be
# safe to embed in DDL.  SaaS field names are alnum/underscore (Salesforce custom
# fields end in __c); reject anything else rather than risk injection.
_SAFE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Postgres column types we allow staging columns to use.
_ALLOWED_PG_TYPES = {
    "text",
    "boolean",
    "integer",
    "double precision",
    "date",
    "timestamptz",
    "jsonb",
}


def _validate_ident(name: str) -> str:
    if not name or not _SAFE_IDENT.match(name):
        raise ValueError(f"Unsafe SQL identifier: {name!r}")
    return name


def _validate_pg_type(pg_type: str) -> str:
    if pg_type not in _ALLOWED_PG_TYPES:
        raise ValueError(f"Unsupported staging column type: {pg_type!r}")
    return pg_type


def all_columns(
    base: list[StagingColumn], selected: list[StagingColumn]
) -> list[StagingColumn]:
    """Combine base + selected columns and append the raw_json column.

    De-duplicates by name (base columns win) so a selected field that collides
    with a system column does not produce a duplicate.
    """
    seen: set[str] = set()
    result: list[StagingColumn] = []
    for col in [*base, *selected]:
        if col.name in seen:
            continue
        seen.add(col.name)
        result.append(col)
    if RAW_JSON_KEY not in seen:
        result.append(StagingColumn(name=RAW_JSON_KEY, pg_type="jsonb"))
    return result


async def create_staging_table(
    session: AsyncSession,
    *,
    schema: str,
    table: str,
    columns: list[StagingColumn],
    id_column: str,
) -> None:
    """Create the staging schema + table if they do not already exist."""
    _validate_ident(schema)
    _validate_ident(table)
    _validate_ident(id_column)

    col_defs: list[str] = []
    for col in columns:
        _validate_ident(col.name)
        _validate_pg_type(col.pg_type)
        pk = " PRIMARY KEY" if col.name == id_column else ""
        col_defs.append(f'"{col.name}" {col.pg_type}{pk}')

    await session.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
    ddl = (
        f'CREATE TABLE IF NOT EXISTS "{schema}"."{table}" (\n  '
        + ",\n  ".join(col_defs)
        + "\n)"
    )
    await session.execute(text(ddl))
    logger.info("Created staging table %s.%s (%d cols)", schema, table, len(columns))


async def upsert_records(
    session: AsyncSession,
    *,
    schema: str,
    table: str,
    columns: list[StagingColumn],
    id_column: str,
    rows: list[dict],
) -> int:
    """Upsert rows into the staging table, keyed on ``id_column``."""
    if not rows:
        return 0
    _validate_ident(schema)
    _validate_ident(table)
    _validate_ident(id_column)

    col_names = [c.name for c in columns]
    placeholders: list[str] = []
    for col in columns:
        if col.pg_type == "jsonb":
            placeholders.append(f"CAST(:{col.name} AS jsonb)")
        elif col.pg_type in ("timestamptz", "date"):
            placeholders.append(f"CAST(:{col.name} AS {col.pg_type})")
        else:
            placeholders.append(f":{col.name}")

    update_cols = [c for c in col_names if c != id_column]
    set_clause = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in update_cols)
    insert_cols = ", ".join(f'"{c}"' for c in col_names)
    sql = (
        f'INSERT INTO "{schema}"."{table}" ({insert_cols})\n'
        f"VALUES ({', '.join(placeholders)})\n"
        f'ON CONFLICT ("{id_column}") DO UPDATE SET {set_clause}'
    )

    params: list[dict] = []
    for row in rows:
        p: dict = {}
        for col in columns:
            val = row.get(col.name)
            if col.pg_type == "jsonb":
                p[col.name] = json.dumps(val) if val is not None else None
            else:
                p[col.name] = val
        params.append(p)

    await session.execute(text(sql), params)
    return len(params)


async def count_rows(session: AsyncSession, *, schema: str, table: str) -> int:
    _validate_ident(schema)
    _validate_ident(table)
    result = await session.execute(
        text(f'SELECT COUNT(*) FROM "{schema}"."{table}"')
    )
    return int(result.scalar() or 0)


async def drop_staging_table(
    session: AsyncSession, *, schema: str, table: str
) -> None:
    _validate_ident(schema)
    _validate_ident(table)
    await session.execute(text(f'DROP TABLE IF EXISTS "{schema}"."{table}"'))
    logger.info("Dropped staging table %s.%s", schema, table)
