"""Query execution routes."""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext, get_request_context
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
from app.services.vdb_routing import (
    VDBInactiveError,
    VDBNotConfiguredError,
    VDBNotFoundError,
    VDBRoutingService,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/query", tags=["query"])

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$.]*$")


class DatasourceQueryRequest(BaseModel):
    tableName: str
    limit: int = Field(default=1000, ge=1, le=10_000)
    project_id: int | None = Field(default=None)
    sql: str | None = Field(default=None)


@router.post("/fetch", response_model=QueryResponse)
async def fetch_table_data(
    payload: QueryRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
) -> QueryResponse:
    routing = VDBRoutingService(session)
    scopes = ScopeProxyService()
    executor = TeiidQueryExecutor(routing=routing, scopes=scopes)
    try:
        result = await executor.fetch_table_data(
            context=context,
            project_id=payload.projectId,
            table_name=payload.tableName,
            column_name=payload.columnName,
            value=payload.value,
            limit=payload.limit,
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

    from app.models.project import Project

    target_user_id = context.user_id

    if payload.project_id is not None:
        project = await session.get(Project, payload.project_id)
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

    settings = get_settings()
    database = f"{user_vdb.vdb_id}.1"

    # Use the fixed 'test/test' credentials registered in WildFly's
    # ApplicationRealm (application-users.properties).  Per-user isolation
    # is provided by the VDB name used as the database — each user connects
    # to their own VDB.  This matches the original Tablescope/Redash approach.
    teiid_username = "test"
    teiid_password = "test"

    teiid_host = settings.teiid_pg_host
    teiid_port = settings.teiid_pg_port

    if payload.sql:
        sql = payload.sql
        if "LIMIT" not in sql.upper():
            sql += f" LIMIT {payload.limit}"
    else:
        sql = f'SELECT * FROM "{payload.tableName}" LIMIT {payload.limit}'

    last_exc: Exception | None = None
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
            # TEIID40041/40042 = stale session after VDB redeploy
            if "TEIID4004" in err_msg and attempt == 0:
                logger.warning("Stale Teiid session, evicting pool and retrying")
                await pool_manager.evict_pool(
                    host=teiid_host,
                    port=teiid_port,
                    database=database,
                    username=teiid_username,
                )
                continue
            logger.error("Query against VDB %s failed: %s", user_vdb.vdb_id, exc)
            raise HTTPException(status_code=502, detail=f"Query failed: {exc}") from exc
    else:
        raise HTTPException(status_code=502, detail=f"Query failed: {last_exc}") from last_exc

    # Build columns positionally and disambiguate duplicate names so that a
    # JOIN selecting columns with the same name from both datasources (e.g.
    # both tables have an "id"/"name"/"date" column) keeps every selected
    # field instead of silently collapsing them via dict(record).
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
