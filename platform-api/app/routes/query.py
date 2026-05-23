"""Query execution routes."""

from __future__ import annotations

import logging
import re
from typing import Any

import asyncpg
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
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Query a datasource (view) directly from the user's VDB.

    This endpoint does not require a project — it queries the user's personal
    VDB directly, which is how uploaded file data is accessed.
    """
    if not _IDENTIFIER_RE.match(payload.tableName):
        raise HTTPException(status_code=400, detail=f"Invalid table name: {payload.tableName!r}")

    user_vdb = await session.scalar(
        select(UserVDB).where(
            UserVDB.tenant_id == context.tenant_id,
            UserVDB.user_id == context.user_id,
        )
    )
    if user_vdb is None:
        raise HTTPException(
            status_code=404,
            detail="No VDB configured for your user. Upload a file first.",
        )
    if not user_vdb.is_active:
        raise HTTPException(status_code=503, detail="Your VDB is not active.")

    settings = get_settings()
    database = f"{user_vdb.vdb_id}.1"

    try:
        pool = await pool_manager.get_pool(
            host=settings.teiid_pg_host,
            port=settings.teiid_pg_port,
            database=database,
            username=user_vdb.vdb_username,
            password=user_vdb.get_decrypted_password(),
        )
        async with pool.acquire() as conn:
            sql = f'SELECT * FROM "{payload.tableName}" LIMIT $1'
            records: list[asyncpg.Record] = await conn.fetch(sql, payload.limit)
    except Exception as exc:
        logger.error("Query against VDB %s failed: %s", user_vdb.vdb_id, exc)
        raise HTTPException(
            status_code=502,
            detail=f"Query failed: {exc}",
        ) from exc

    columns: list[str] = list(records[0].keys()) if records else []
    rows = [dict(record) for record in records]

    return {"columns": columns, "rows": rows}
