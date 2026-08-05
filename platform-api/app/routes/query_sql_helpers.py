"""SQL building/execution helpers shared across the routes layer.

Pure helpers with no FastAPI decorators: VDB resolution, Teiid execution,
aggregate/timestamp casting, and the AI ``fix-sql`` repair loop. ``query.py``'s
own endpoints and several sibling route modules depend on these directly.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.config import get_settings
from app.models.user_vdb import UserVDB
from app.services import ai_intelligence_client
from app.services.connection_pool import pool_manager
from app.services.teiid_sql import (
    normalize_teiid_identifiers,
    normalize_teiid_timestamps,
)

logger = logging.getLogger(__name__)


async def _resolve_vdb_database(
    *,
    session: AsyncSession,
    context: RequestContext,
    project_id: int | None,
) -> str:
    """Resolve the Teiid database name (``<vdb_id>.1``) for a request.

    When ``project_id`` is provided and the project is shared, the query runs
    against the project owner's VDB (where the views live). Otherwise it
    targets the current user's personal VDB.
    """
    from app.models.project import Project

    target_user_id = context.user_id
    if project_id is not None:
        project = await session.get(Project, project_id)
        if project is not None and project.is_shared and project.owner_id:
            target_user_id = project.owner_id

    user_vdb = await session.scalar(
        select(UserVDB).where(
            UserVDB.tenant_id == context.tenant_id,
            UserVDB.user_id == target_user_id,
        )
    )
    if user_vdb is None:
        raise HTTPException(
            status_code=404,
            detail="No VDB configured. Upload a file first.",
        )
    if not user_vdb.is_active:
        raise HTTPException(status_code=503, detail="VDB is not active.")
    return f"{user_vdb.vdb_id}.1"


async def _sample_project_columns(
    *,
    database: str,
    tables: list[str],
    teiid_host: str | None = None,
    teiid_port: int | None = None,
) -> dict[str, str]:
    """Return one non-empty sample value per column across the given tables."""
    samples: dict[str, str] = {}
    for view_name in tables:
        try:
            result = await _run_sql(
                database=database,
                sql=f'SELECT * FROM "{view_name}" LIMIT 25',
                teiid_host=teiid_host,
                teiid_port=teiid_port,
            )
        except Exception:
            continue
        for row in result.get("rows", [])[:25]:
            for col, val in row.items():
                if col in samples:
                    continue
                text = str(val).strip() if val is not None else ""
                if text:
                    samples[col] = text[:40]
    return samples


async def _run_sql(
    *,
    database: str,
    sql: str,
    teiid_host: str | None = None,
    teiid_port: int | None = None,
) -> dict[str, Any]:
    """Execute SQL against a Teiid VDB and return ``{columns, rows}``.

    Duplicate column names (common in JOINs that select same-named columns from
    both datasources) are disambiguated with ``_1``/``_2`` suffixes so every
    selected field survives instead of being collapsed by ``dict(record)``.

    ``teiid_host``/``teiid_port`` are supplied by the tenant Teiid resolver: a
    tenant bound to a dedicated data plane is routed to its own container, while
    unbound tenants fall back to the shared global Teiid.
    """
    settings = get_settings()
    # Fixed 'test/test' credentials registered in WildFly's ApplicationRealm;
    # per-user isolation comes from the per-user VDB used as the database.
    teiid_username = "test"
    teiid_password = "test"
    teiid_host = teiid_host or settings.teiid_pg_host
    teiid_port = teiid_port or settings.teiid_pg_port

    last_exc: Exception | None = None
    records: list[Any] = []
    for attempt in range(2):
        try:
            pool = await pool_manager.get_pool(
                host=teiid_host,
                port=teiid_port,
                database=database,
                username=teiid_username,
                password=teiid_password,
            )
            async with pool.acquire() as conn:
                records = list(await conn.fetch(sql))
            break
        except Exception as exc:
            last_exc = exc
            err_msg = str(exc)
            if "TEIID4004" in err_msg and attempt == 0:
                logger.warning("Stale Teiid session, evicting pool and retrying")
                await pool_manager.evict_pool(
                    host=teiid_host,
                    port=teiid_port,
                    database=database,
                    username=teiid_username,
                )
                continue
            logger.error("Query against database %s failed: %s", database, exc)
            raise HTTPException(status_code=502, detail=f"Query failed: {exc}") from exc
    else:
        raise HTTPException(status_code=502, detail=f"Query failed: {last_exc}") from last_exc

    if records:
        raw_cols = list(records[0].keys())
        seen: dict[str, int] = {}
        columns: list[str] = []
        for name in raw_cols:
            if name in seen:
                seen[name] += 1
                columns.append(f"{name}_{seen[name]}")
            else:
                seen[name] = 0
                columns.append(name)
        rows = [
            {columns[i]: value for i, value in enumerate(record.values())}
            for record in records
        ]
    else:
        columns = []
        rows = []
    return {"columns": columns, "rows": rows}


# Regex to add CAST(... AS double) inside SUM/AVG/MIN/MAX so aggregations work
# on CSV columns that Teiid imports as string type. COUNT is excluded (works on
# any type). Matches e.g. SUM("revenue") or AVG(col) but NOT already-cast
# expressions like SUM(CAST(...)).
_AGG_CAST_RE = re.compile(
    r'\b(SUM|AVG|MIN|MAX)\(\s*(?!CAST\b)(\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_$.]*)\s*\)',
    re.IGNORECASE,
)


def _cast_timestampdiff(sql: str) -> str:
    """Wrap every TIMESTAMPDIFF(...) call in CAST(... AS double).

    TIMESTAMPDIFF returns a bigint; the driver cannot decode the result of an
    aggregate over it (AVG/SUM) across Teiid's pg wire ("insufficient data in
    buffer"). Casting the difference to double keeps day/month counts exact and
    lets aggregation decode correctly. Already-cast calls are left untouched.
    """
    out: list[str] = []
    i = 0
    lowered = sql.lower()
    token = "timestampdiff"
    while True:
        idx = lowered.find(token, i)
        if idx == -1:
            out.append(sql[i:])
            break
        # Locate the opening paren after the function name.
        j = idx + len(token)
        while j < len(sql) and sql[j].isspace():
            j += 1
        if j >= len(sql) or sql[j] != "(":
            out.append(sql[i : idx + len(token)])
            i = idx + len(token)
            continue
        # Match balanced parentheses for the full call.
        depth = 0
        k = j
        while k < len(sql):
            if sql[k] == "(":
                depth += 1
            elif sql[k] == ")":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        if depth != 0:  # unbalanced — leave the remainder untouched
            out.append(sql[i:])
            break
        call = sql[idx : k + 1]
        # Skip if this call is already the argument of a CAST(...).
        prefix = sql[:idx].rstrip()
        if prefix.lower().endswith("cast("):
            out.append(sql[i : k + 1])
        else:
            out.append(sql[i:idx])
            out.append(f"CAST({call} AS double)")
        i = k + 1
    return "".join(out)


def _auto_cast_aggregates(sql: str) -> str:
    """Wrap SUM/AVG/MIN/MAX column arguments with CAST(col AS double).

    Teiid imports CSV columns as string, causing numeric aggregations to fail.
    This transparently casts the argument for the user. TIMESTAMPDIFF results
    (bigint) are also cast so aggregates over date differences decode correctly.
    """
    def _replacer(m: re.Match[str]) -> str:
        func = m.group(1).upper()
        col = m.group(2)
        return f"{func}(CAST({col} AS double))"

    return _cast_timestampdiff(_AGG_CAST_RE.sub(_replacer, sql))


async def _prepare_sql(
    sql: str,
    *,
    table_schema: list[dict[str, Any]],
    column_types: dict[str, str],
    column_samples: dict[str, str],
) -> str:
    """Normalize and repair common AI SQL mistakes before execution."""
    if table_schema:
        sql = normalize_teiid_identifiers(sql, table_schema)
    sql = normalize_teiid_timestamps(
        sql, column_types=column_types, column_samples=column_samples
    )
    sql = _auto_cast_aggregates(sql).rstrip().rstrip(";")
    return sql


async def _execute_sql_with_repair(
    *,
    raw_sql: str,
    tenant_id: int,
    user_id: int,
    project_id: int,
    database: str,
    endpoint: Any,
    table_schema: list[dict[str, Any]],
    allowed_tables: list[str],
    column_types: dict[str, str],
    column_samples: dict[str, str],
    max_attempts: int = 3,
) -> tuple[dict[str, Any] | None, str]:
    """Run ``raw_sql`` after normalization, calling ``fix-sql`` on failure.

    Returns ``(result, final_sql)``. ``result`` is ``None`` only when every
    repair attempt fails, in which case ``final_sql`` is the last attempted
    SQL and the caller should surface the error.
    """

    def _is_source_or_schema_error(err: str) -> bool:
        # These errors indicate an unavailable source, bad gateway, missing
        # table/column, or runtime source failure. Asking an LLM to rewrite
        # the SQL cannot resolve them and only consumes time / queue slots.
        patterns = [
            r"TEIID30504",
            r"TEIID30498",
            r"TEIID30492",
            r"TEIID30496",
            r"Group does not exist",
            r"is not defined by any relevant group",
            r"Table .* does not exist",
            r"HTTP \d+",
            r"Bad Gateway",
            r"Connection refused",
            r"Connection timed out",
            r"No route to host",
            r"Capabilities for .* were not available",
            r"Could not execute generated SQL",
        ]
        lowered = err.lower()
        return any(re.search(p, lowered, re.IGNORECASE) for p in patterns)

    final_sql = await _prepare_sql(
        raw_sql,
        table_schema=table_schema,
        column_types=column_types,
        column_samples=column_samples,
    )
    last_error = ""
    for attempt in range(max_attempts):
        try:
            result = await _run_sql(
                database=database,
                sql=final_sql,
                teiid_host=endpoint.pg_host,
                teiid_port=endpoint.pg_port,
            )
            return result, final_sql
        except HTTPException as exc:
            last_error = str(exc.detail)
            if _is_source_or_schema_error(last_error) or attempt >= max_attempts - 1:
                break
            fixed = await ai_intelligence_client.fix_sql(
                tenant_id=tenant_id,
                user_id=user_id,
                project_id=project_id,
                sql=final_sql,
                error=last_error,
                allowed_tables=allowed_tables,
                table_schema=table_schema,
            )
            if not fixed:
                break
            final_sql = await _prepare_sql(
                fixed,
                table_schema=table_schema,
                column_types=column_types,
                column_samples=column_samples,
            )

    return None, final_sql
