"""Database source connection wizard: test / schemas / tables / columns / preview.

Split from ``database_sources.py``; siblings:
``database_sources_saved_connections.py`` and ``database_sources_lifecycle.py``.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.database_connection import DatabaseConnection
from app.schemas.database_source import (
    ColumnRequest,
    ColumnsResponse,
    PreviewRequest,
    PreviewResponse,
    SchemaRequest,
    SchemasResponse,
    TableRequest,
    TablesResponse,
    TestConnectionResponse,
)
from app.services import database_introspection_service as intro
from app.services.crypto import decrypt_secret
from app.services.database_introspection_service import (
    ConnectionParams,
    DatabaseIntrospectionError,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/database-sources", tags=["database-sources"])


def _params(body) -> ConnectionParams:
    return ConnectionParams(
        db_type=body.db_type or "",
        host=body.host or "",
        port=body.port,
        database_name=body.database_name or "",
        username=body.username or "",
        password=body.password or "",
        ssl_mode=getattr(body, "ssl_mode", None),
    )


async def _resolve_params(
    body, session: AsyncSession, context: RequestContext
) -> ConnectionParams:
    """Build :class:`ConnectionParams` from the request.

    If ``connection_id`` is set, load the saved connection profile (scoped to
    the caller's tenant) and use its stored, decrypted credentials.  Inline
    fields on the body override the saved values when provided (e.g. a new
    password), which keeps the wizard flexible.
    """
    conn_id = getattr(body, "connection_id", None)
    if conn_id is None:
        return _params(body)

    conn = await session.get(DatabaseConnection, conn_id)
    if conn is None or conn.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Saved connection not found")

    password = body.password
    if not password and conn.password_encrypted:
        password = decrypt_secret(conn.password_encrypted)

    return ConnectionParams(
        db_type=body.db_type or conn.db_type,
        host=body.host or conn.host,
        port=body.port or conn.port,
        database_name=body.database_name or conn.database_name,
        username=body.username or conn.username,
        password=password or "",
        ssl_mode=body.ssl_mode or conn.ssl_mode,
    )


@router.post("/test", response_model=TestConnectionResponse)
async def test_connection(
    body: SchemaRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> TestConnectionResponse:
    params = await _resolve_params(body, session, context)
    try:
        await run_in_threadpool(intro.test_connection, params)
    except DatabaseIntrospectionError as exc:
        return TestConnectionResponse(success=False, message=str(exc))
    return TestConnectionResponse(success=True, message="Connection successful")


@router.post("/schemas", response_model=SchemasResponse)
async def list_schemas(
    body: SchemaRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> SchemasResponse:
    params = await _resolve_params(body, session, context)
    try:
        schemas = await run_in_threadpool(intro.list_schemas, params)
    except DatabaseIntrospectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SchemasResponse(schemas=schemas)


@router.post("/tables", response_model=TablesResponse)
async def list_tables(
    body: TableRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> TablesResponse:
    params = await _resolve_params(body, session, context)
    try:
        tables = await run_in_threadpool(
            intro.list_tables, params, body.schema_name
        )
    except DatabaseIntrospectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TablesResponse(tables=tables)


@router.post("/columns", response_model=ColumnsResponse)
async def list_columns(
    body: ColumnRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> ColumnsResponse:
    params = await _resolve_params(body, session, context)
    try:
        columns = await run_in_threadpool(
            intro.list_columns, params, body.schema_name, body.table_name
        )
    except DatabaseIntrospectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ColumnsResponse(columns=columns)


@router.post("/preview", response_model=PreviewResponse)
async def preview_table(
    body: PreviewRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> PreviewResponse:
    """Return a small sample of rows so the user can review a table's data."""
    params = await _resolve_params(body, session, context)
    try:
        result = await run_in_threadpool(
            intro.sample_rows,
            params,
            body.schema_name,
            body.table_name,
            body.limit,
        )
    except DatabaseIntrospectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PreviewResponse(columns=result["columns"], rows=result["rows"])
