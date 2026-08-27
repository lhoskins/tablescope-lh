"""SQL building/execution helpers shared across the routes layer.

Pure helpers with no FastAPI decorators: VDB resolution, Teiid execution,
aggregate/timestamp casting, and the AI ``fix-sql`` repair loop. ``query.py``'s
own endpoints and several sibling route modules depend on these directly.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.config import get_settings
from app.models.user_vdb import UserVDB
from app.services.connection_pool import pool_manager
from app.services.sql_repair_agent import run_repair_loop
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
            is_connection_timeout = isinstance(
                exc, TimeoutError | asyncio.TimeoutError | ConnectionError | OSError
            )
            lowered_msg = err_msg.lower()
            # "Capabilities for X were not available" (TEIID30498/30492/30496) is
            # Teiid's per-source translator metadata not being loaded yet -- the
            # exact cold-VDB condition vdb_warming.py exists to avoid, surfaced
            # instead of prevented when a query lands before warming finishes.
            # It clears on its own once the source is queried once, so it is
            # retried here the same as a stale session / connection timeout
            # rather than failing outright.
            is_cold_capabilities = "capabilities for" in lowered_msg and (
                "were not available" in lowered_msg or "not available" in lowered_msg
            )
            should_retry = (
                attempt == 0
                and (
                    "TEIID4004" in err_msg
                    or is_connection_timeout
                    or "timeout" in lowered_msg
                    or is_cold_capabilities
                )
            )
            if should_retry:
                logger.warning(
                    "Teiid query failed, evicting pool and retrying: %s", exc
                )
                await pool_manager.evict_pool(
                    host=teiid_host,
                    port=teiid_port,
                    database=database,
                    username=teiid_username,
                )
                if is_cold_capabilities:
                    # Give translator metadata loading, which is still in
                    # flight, a moment to finish rather than immediately
                    # re-hitting the same not-yet-ready state.
                    await asyncio.sleep(2)
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


# Regex to add CAST(... AS double) inside SUM/AVG so aggregations work on CSV
# columns that Teiid imports as string type. Matches e.g. SUM("revenue") or
# AVG(col) but NOT already-cast expressions like SUM(CAST(...)).
#
# MIN/MAX are deliberately excluded: unlike SUM/AVG, which are mathematically
# meaningless on a string and MUST be cast to work at all, MIN/MAX are valid
# on any orderable type -- a string/date column sorts fine as-is in the
# common case (consistently formatted dates, zero-padded numbers). Casting
# them unconditionally traded a narrow correctness win (an inconsistently
# formatted numeric-as-string column) for a hard failure on every date/text
# column: MIN(r."Month") -> MIN(CAST(r."Month" AS double)) ->
# TEIID30328 "Unable to evaluate convert(...)". COUNT is excluded too (works
# on any type, never needs a cast).
#
# The quoted-column alternative accepts an optional qualifying prefix --
# either an unquoted alias (r."RevenueUSD") or a QUOTED table name
# ("sales_revenue_monthly_CSV"."RevenueUSD") -- as well as a bare quoted
# column ("RevenueUSD"). Two distinct qualified forms used to fall through
# uncast entirely, each only caught once reproduced live:
#   - unquoted-alias prefix (r."RevenueUSD"): the unquoted alternative's
#     character class allows a dotted path like `r.` but not the quote that
#     follows it, so the whole call failed to match.
#   - quoted-table-name prefix ("sales_revenue_monthly_CSV"."RevenueUSD"):
#     normalize_teiid_identifiers (which runs before this, in _prepare_sql)
#     quotes real table names, and the original fix only ever accepted an
#     UNQUOTED prefix -- so a query the model qualified with the full table
#     name, rather than an alias, still fell through uncast after
#     normalization even though the alias-qualified form worked.
# Both are rejected by Teiid with TEIID30492 "aggregate function SUM cannot
# be used with non-numeric expressions" once a query is written to qualify
# every column, as multi-table joins must.
_AGG_CAST_RE = re.compile(
    r'\b(SUM|AVG)\(\s*(?!CAST\b)'
    r'((?:(?:[A-Za-z_][A-Za-z0-9_$]*|\"[^\"]+\")\.)?\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_$.]*)'
    r'\s*\)',
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
    """Wrap SUM/AVG column arguments with CAST(col AS double).

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


_LIMIT_RE = re.compile(r"\blimit\s+\d+\s*$", re.IGNORECASE)


def _apply_pagination(sql: str, limit: int | None, offset: int) -> str:
    if limit is None:
        return sql
    trimmed = sql.strip().rstrip(";").rstrip()
    if _LIMIT_RE.search(trimmed):
        return trimmed
    return f"{trimmed} LIMIT {limit} OFFSET {offset}"


def _is_source_or_schema_error(err: str) -> bool:
    """True for an error no SQL rewrite could ever fix.

    These indicate an unavailable source, bad gateway, missing table/column,
    or runtime source failure. Asking the repair agent to rewrite the SQL
    cannot resolve them and only consumes time / queue slots -- a production
    trace showed these recurring unchanged across repair attempts against the
    same data sources, each attempt paying a full Teiid round trip plus a
    repair-agent call before giving up, multiplying a single slow, unfixable
    query into a much slower one.
    """
    patterns = [
        r"TEIID30504",
        r"TEIID30498",
        r"TEIID30492",
        r"TEIID30496",
        # Function-dialect mismatches (e.g. the model reaching for
        # DATEADD/DATE_FORMAT, which Teiid does not implement) and hard
        # parse errors.
        r"TEIID30068",
        r"TEIID30328",
        r"TEIID30384",
        r"TEIID31100",
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
    limit: int | None = None,
    offset: int = 0,
) -> tuple[dict[str, Any] | None, str, str]:
    """Run ``raw_sql`` after normalization, repairing via the SQL self-repair
    agent (``sql_repair_agent.run_repair_loop``, shared with the chat
    ask-and-run path) on failure.

    Returns ``(result, final_sql, bounded_sql)``. ``result`` is ``None`` only
    when every repair attempt fails, in which case ``final_sql`` is the last
    attempted SQL and the caller should surface the error. ``bounded_sql``
    includes any requested LIMIT/OFFSET.
    """

    async def _normalize(candidate: str) -> str:
        return await _prepare_sql(
            candidate,
            table_schema=table_schema,
            column_types=column_types,
            column_samples=column_samples,
        )

    async def _execute(candidate: str) -> dict[str, Any]:
        bounded = _apply_pagination(candidate, limit, offset)
        return await _run_sql(
            database=database,
            sql=bounded,
            teiid_host=endpoint.pg_host,
            teiid_port=endpoint.pg_port,
        )

    result, final_sql, _last_error = await run_repair_loop(
        initial_sql=raw_sql,
        tenant_id=tenant_id,
        user_id=user_id,
        project_id=project_id,
        allowed_tables=allowed_tables,
        table_schema=table_schema,
        column_samples=column_samples,
        column_types=column_types,
        normalize=_normalize,
        execute=_execute,
        is_unfixable_error=_is_source_or_schema_error,
        max_execute_attempts=max_attempts,
    )
    bounded_sql = _apply_pagination(final_sql, limit, offset)
    return result, final_sql, bounded_sql
