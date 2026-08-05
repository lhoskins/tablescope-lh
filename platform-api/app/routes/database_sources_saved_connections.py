"""Saved database connection profiles and the unified connected-sources list.

Split from ``database_sources.py``; siblings:
``database_sources_connection.py`` and ``database_sources_lifecycle.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.database_connection import DatabaseConnection
from app.models.database_data_source import DatabaseDataSource
from app.models.database_data_source_assignment import (
    DatabaseDataSourceAssignment,
)
from app.models.user import User
from app.routes.database_sources_connection import _resolve_params
from app.schemas.data_source_assignment import ConnectedSource
from app.schemas.database_source import (
    SaveConnectionRequest,
    SavedConnectionRead,
    TestConnectionResponse,
    UpdateConnectionRequest,
)
from app.services import database_introspection_service as intro
from app.services.crypto import decrypt_secret, encrypt_secret
from app.services.database_introspection_service import (
    ConnectionParams,
    DatabaseIntrospectionError,
)

router = APIRouter(prefix="/database-sources", tags=["database-sources"])


# ── Saved connection profiles (item 5) ──────────────────────────────


@router.get("/connections", response_model=list[SavedConnectionRead])
async def list_saved_connections(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> list[SavedConnectionRead]:
    rows = (
        await session.scalars(
            select(DatabaseConnection).where(
                DatabaseConnection.tenant_id == context.tenant_id,
                DatabaseConnection.created_by == context.user_id,
            )
        )
    ).all()
    return [SavedConnectionRead(**r.to_dict()) for r in rows]


@router.get("/connected", response_model=list[ConnectedSource])
async def list_connected_databases(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[ConnectedSource]:
    """Unified "Connected Databases" list: owned connections + assigned sources.

    Owned items are the caller's saved connection profiles (editable).
    Assigned items are datasources an Admin/DB Admin shared with the caller;
    their credentials are never exposed and cannot be edited.
    """
    items: list[ConnectedSource] = []

    owned = (
        await session.scalars(
            select(DatabaseConnection).where(
                DatabaseConnection.tenant_id == context.tenant_id,
                DatabaseConnection.created_by == context.user_id,
            )
        )
    ).all()
    for c in owned:
        items.append(
            ConnectedSource(
                id=f"owned-{c.id}",
                source="owned",
                database_connection_id=c.id,
                display_name=c.name,
                db_type=c.db_type,
                host=c.host,
                database=c.database_name,
                read_only=False,
                can_edit_connection=True,
                can_select=True,
            )
        )

    assignments = (
        await session.scalars(
            select(DatabaseDataSourceAssignment).where(
                DatabaseDataSourceAssignment.tenant_id == context.tenant_id,
                DatabaseDataSourceAssignment.assigned_user_id
                == context.user_id,
                DatabaseDataSourceAssignment.is_active.is_(True),
            )
        )
    ).all()
    for a in assignments:
        source = await session.get(
            DatabaseDataSource, a.database_data_source_id
        )
        if source is None or source.archived:
            continue
        assigner = (
            await session.get(User, a.assigned_by) if a.assigned_by else None
        )
        assigned_by_name = None
        if assigner is not None:
            assigned_by_name = assigner.display_name or assigner.email
        items.append(
            ConnectedSource(
                id=f"assigned-{a.id}",
                source="assigned",
                database_data_source_id=a.database_data_source_id,
                database_connection_id=a.database_connection_id,
                display_name=a.friendly_name,
                db_type=source.db_type,
                host=source.host,
                database=source.database_name,
                read_only=a.read_only,
                assigned_by=assigned_by_name,
                can_edit_connection=False,
                can_select=True,
            )
        )

    return items


@router.post("/connections", response_model=SavedConnectionRead)
async def create_saved_connection(
    body: SaveConnectionRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> SavedConnectionRead:
    params = await _resolve_params(body, session, context)
    try:
        intro.get_db_type_config(params.db_type)
        await run_in_threadpool(intro.test_connection, params)
    except DatabaseIntrospectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    conn = DatabaseConnection(
        tenant_id=context.tenant_id,
        created_by=context.user_id,
        name=body.name,
        db_type=params.db_type,
        host=params.host,
        port=params.resolved_port,
        database_name=params.database_name,
        username=params.username,
        password_encrypted=encrypt_secret(params.password) if params.password else None,
        ssl_mode=params.ssl_mode,
        last_tested_at=datetime.now(UTC),
    )
    session.add(conn)
    await session.commit()
    await session.refresh(conn)
    return SavedConnectionRead(**conn.to_dict())


@router.patch("/connections/{connection_id}", response_model=SavedConnectionRead)
async def update_saved_connection(
    connection_id: int,
    body: UpdateConnectionRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> SavedConnectionRead:
    conn = await session.get(DatabaseConnection, connection_id)
    if conn is None or conn.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Saved connection not found")

    # Build effective params: body overrides, falling back to stored values.
    params = ConnectionParams(
        db_type=body.db_type or conn.db_type,
        host=body.host or conn.host,
        port=body.port or conn.port,
        database_name=body.database_name or conn.database_name,
        username=body.username or conn.username,
        password=(
            body.password
            or (decrypt_secret(conn.password_encrypted) if conn.password_encrypted else "")
        ),
        ssl_mode=body.ssl_mode if body.ssl_mode is not None else conn.ssl_mode,
    )
    try:
        intro.get_db_type_config(params.db_type)
        await run_in_threadpool(intro.test_connection, params)
    except DatabaseIntrospectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if body.name:
        conn.name = body.name
    conn.db_type = params.db_type
    conn.host = params.host
    conn.port = params.resolved_port
    conn.database_name = params.database_name
    conn.username = params.username
    if body.password:
        conn.password_encrypted = encrypt_secret(body.password)
    conn.ssl_mode = params.ssl_mode
    conn.last_tested_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(conn)
    return SavedConnectionRead(**conn.to_dict())


@router.post(
    "/connections/{connection_id}/test", response_model=TestConnectionResponse
)
async def test_saved_connection(
    connection_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> TestConnectionResponse:
    conn = await session.get(DatabaseConnection, connection_id)
    if conn is None or conn.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Saved connection not found")
    params = ConnectionParams(
        db_type=conn.db_type,
        host=conn.host,
        port=conn.port,
        database_name=conn.database_name,
        username=conn.username,
        password=(
            decrypt_secret(conn.password_encrypted) if conn.password_encrypted else ""
        ),
        ssl_mode=conn.ssl_mode,
    )
    try:
        await run_in_threadpool(intro.test_connection, params)
    except DatabaseIntrospectionError as exc:
        return TestConnectionResponse(success=False, message=str(exc))
    conn.last_tested_at = datetime.now(UTC)
    await session.commit()
    return TestConnectionResponse(success=True, message="Connection successful")


@router.delete("/connections/{connection_id}")
async def delete_saved_connection(
    connection_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict:
    conn = await session.get(DatabaseConnection, connection_id)
    if conn is None or conn.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Saved connection not found")
    if conn.created_by != context.user_id and context.role != "admin":
        raise HTTPException(status_code=403, detail="Not allowed to delete this connection")
    await session.delete(conn)
    await session.commit()
    return {"status": "deleted", "id": connection_id}
