"""Query execution routes."""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.membership import require_membership
from app.auth.rbac import Role, require_role
from app.config import get_settings
from app.database import get_db
from app.models.user_vdb import UserVDB
from app.schemas.query import QueryRequest, QueryResponse
from app.services.connection_pool import pool_manager
from app.services.query_executor import (
    QueryValidationError,
    TeiidQueryExecutor,
)
from app.services.scope_proxy import ScopeProxyService
from app.services.tenant_teiid_resolver import TenantTeiidResolver
from app.services.vdb_routing import (
    VDBInactiveError,
    VDBNotConfiguredError,
    VDBNotFoundError,
    VDBRoutingService,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/query", tags=["query"])

# View names can start with a digit (e.g. a file named "0_revenue.csv" maps to
# the view "0_revenueTest_CSV"); the name is always emitted inside double quotes
# in generated SQL, so a leading digit is safe.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_$.]*$")


class DatasourceQueryRequest(BaseModel):
    tableName: str
    limit: int = Field(default=1000, ge=1, le=10_000)
    project_id: int | None = Field(default=None)
    sql: str | None = Field(default=None)


@router.post("/fetch", response_model=QueryResponse)
async def fetch_table_data(
    payload: QueryRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_membership),
) -> QueryResponse:
    routing = VDBRoutingService(session)
    scopes = ScopeProxyService()
    executor = TeiidQueryExecutor(routing=routing, scopes=scopes)
    endpoint = await TenantTeiidResolver(session).resolve_for_org(context.tenant_id)
    try:
        result = await executor.fetch_table_data(
            context=context,
            project_id=payload.projectId,
            table_name=payload.tableName,
            column_name=payload.columnName,
            value=payload.value,
            limit=payload.limit,
            teiid_host=endpoint.pg_host,
            teiid_port=endpoint.pg_port,
        )
    except QueryValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (VDBNotConfiguredError, VDBNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VDBInactiveError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        await scopes.aclose()

    return QueryResponse(
        columns=result.columns,
        rows=result.rows,
        drilldownUsed=result.drilldown_used,
        targetTable=result.target_table,
        targetColumn=result.target_column,
    )


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


@router.post("/datasource")
async def query_datasource(
    payload: DatasourceQueryRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """Query a datasource (view) from the appropriate VDB.

    When project_id is provided and the project is shared, the query runs
    against the project owner's VDB (where the views live). Otherwise it
    queries the current user's personal VDB.
    """
    if not _IDENTIFIER_RE.match(payload.tableName):
        raise HTTPException(status_code=400, detail=f"Invalid table name: {payload.tableName!r}")

    database = await _resolve_vdb_database(
        session=session, context=context, project_id=payload.project_id
    )

    endpoint = await TenantTeiidResolver(session).resolve_for_org(context.tenant_id)

    if payload.sql:
        sql = _auto_cast_aggregates(payload.sql).rstrip().rstrip(";")
    else:
        sql = f'SELECT * FROM "{payload.tableName}" LIMIT {payload.limit}'

    return await _run_sql(
        database=database,
        sql=sql,
        teiid_host=endpoint.pg_host,
        teiid_port=endpoint.pg_port,
    )
