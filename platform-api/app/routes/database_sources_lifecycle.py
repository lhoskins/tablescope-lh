"""Database data source lifecycle: create, list, archive, delete, reconcile.

Split from ``database_sources.py``; siblings:
``database_sources_connection.py`` and ``database_sources_saved_connections.py``.
``find_query_dependencies`` lives here and is imported by ``upload.py`` and
``saas_sources.py``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.database_connection import DatabaseConnection
from app.models.database_data_source import DatabaseDataSource, DataSourceColumn
from app.models.project import Project
from app.models.user_vdb import UserVDB
from app.routes.database_sources_connection import _resolve_params
from app.schemas.archive_source import ArchiveSourceRequest
from app.schemas.database_source import CreateDatabaseSourceRequest
from app.services import database_introspection_service as intro
from app.services.crypto import encrypt_secret
from app.services.database_introspection_service import DatabaseIntrospectionError
from app.services.teiid_registration_service import (
    TeiidRegistrationError,
    TeiidRegistrationService,
    generate_teiid_names,
    generate_view_name,
    reconcile_database_sources,
)
from app.services.tenant_teiid_resolver import TenantTeiidResolver

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/database-sources", tags=["database-sources"])


@router.post("")
async def create_database_source(
    body: CreateDatabaseSourceRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict:
    """Validate, introspect, encrypt, persist, register in Teiid."""
    # Resolve credentials (inline or from a saved connection profile).
    params = await _resolve_params(body, session, context)

    # 1. Validate db type early (clear error for unsupported types).
    try:
        intro.get_db_type_config(params.db_type)
    except DatabaseIntrospectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 2. Test connection.
    try:
        await run_in_threadpool(intro.test_connection, params)
    except DatabaseIntrospectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 3. Introspect columns.
    try:
        columns = await run_in_threadpool(
            intro.list_columns, params, body.schema_name, body.table_name
        )
    except DatabaseIntrospectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Optional project ownership check.
    if body.project_id is not None:
        project = await session.get(Project, body.project_id)
        if project is None or project.tenant_id != context.tenant_id:
            raise HTTPException(status_code=404, detail="Project not found")

    # Resolve caller's VDB (where the model + view will be registered).
    user_vdb = await session.scalar(
        select(UserVDB).where(
            UserVDB.tenant_id == context.tenant_id,
            UserVDB.user_id == context.user_id,
        )
    )
    if user_vdb is None:
        raise HTTPException(
            status_code=400,
            detail="No VDB configured for your user. Upload a file or contact an admin.",
        )

    # Reject duplicate display names within the same tenant/project scope.
    dup = await session.scalar(
        select(DatabaseDataSource).where(
            DatabaseDataSource.tenant_id == context.tenant_id,
            DatabaseDataSource.created_by == context.user_id,
            DatabaseDataSource.display_name == body.display_name,
        )
    )
    if dup is not None:
        raise HTTPException(
            status_code=409,
            detail=f"A data source named '{body.display_name}' already exists.",
        )

    # 4. Optionally persist a reusable connection profile (item 5).
    if body.save_connection:
        existing_conn = await session.scalar(
            select(DatabaseConnection).where(
                DatabaseConnection.tenant_id == context.tenant_id,
                DatabaseConnection.created_by == context.user_id,
                DatabaseConnection.host == params.host,
                DatabaseConnection.port == params.resolved_port,
                DatabaseConnection.database_name == params.database_name,
                DatabaseConnection.username == params.username,
            )
        )
        if existing_conn is None:
            session.add(
                DatabaseConnection(
                    tenant_id=context.tenant_id,
                    created_by=context.user_id,
                    name=body.connection_name or body.display_name,
                    db_type=params.db_type,
                    host=params.host,
                    port=params.resolved_port,
                    database_name=params.database_name,
                    username=params.resolved_username,
                    password_encrypted=encrypt_secret(params.password)
                    if params.password
                    else None,
                    ssl_mode=params.ssl_mode,
                )
            )

    # 5. Encrypt password + persist row (draft).
    ds = DatabaseDataSource(
        tenant_id=context.tenant_id,
        project_id=body.project_id,
        created_by=context.user_id,
        display_name=body.display_name,
        source_type="database_table",
        db_type=params.db_type,
        host=params.host,
        port=params.resolved_port,
        database_name=params.database_name,
        schema_name=body.schema_name,
        table_name=body.table_name,
        username=params.resolved_username,
        password_encrypted=encrypt_secret(params.password) if params.password else None,
        ssl_mode=params.ssl_mode,
        teiid_model_name="",
        teiid_table_name="",
        teiid_view_name="",
        teiid_jndi_name="",
        status="draft",
        last_test_status="success",
        last_test_message="Connection successful",
        last_tested_at=datetime.now(UTC),
    )
    session.add(ds)
    await session.flush()  # assign ds.id

    names = generate_teiid_names(
        data_source_id=ds.id, db_type=params.db_type, table_name=body.table_name
    )
    view_name = generate_view_name(
        display_name=body.display_name, db_type=params.db_type
    )
    ds.teiid_model_name = names["model_name"]
    ds.teiid_table_name = names["teiid_table_name"]
    ds.teiid_jndi_name = names["jndi_name"]
    ds.teiid_view_name = view_name

    teiid_columns = [
        {
            "name": c["name"],
            "name_in_source": c.get("name_in_source", c["name"]),
            "teiid_type": intro.map_to_teiid_type(c.get("type", "")),
        }
        for c in columns
    ]
    for c in columns:
        session.add(
            DataSourceColumn(
                data_source_id=ds.id,
                column_name=c["name"],
                ordinal_position=c.get("ordinal_position"),
                data_type=c.get("type"),
                nullable=c.get("nullable"),
                primary_key=c.get("primary_key", False),
                created_at=datetime.now(UTC),
            )
        )

    # 5. Register in Teiid (model + view + redeploy).
    endpoint = await TenantTeiidResolver(session).resolve_for_org(context.tenant_id)
    reg = TeiidRegistrationService(servlet_url=endpoint.servlet_url)
    try:
        await reg.register_database_source(
            vdb_id=user_vdb.vdb_id,
            org_id=context.tenant_id,
            user_id=context.user_id,
            db_type=params.db_type,
            host=params.host,
            port=params.resolved_port,
            database_name=params.database_name,
            schema_name=intro.source_identifier(params.db_type, body.schema_name),
            table_name=intro.source_identifier(params.db_type, body.table_name)
            or body.table_name,
            username=params.resolved_username,
            password=params.password,
            ssl_mode=params.ssl_mode,
            model_name=names["model_name"],
            teiid_table_name=names["teiid_table_name"],
            jndi_name=names["jndi_name"],
            ds_name=names["ds_name"],
            view_name=view_name,
            columns=teiid_columns,
        )
    except TeiidRegistrationError as exc:
        await session.rollback()
        # Keep the raw WildFly/Teiid error in the logs only; the verbatim CLI
        # JSON is noisy and unhelpful (and potentially sensitive) for end users.
        logger.error("Teiid registration failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail=(
                "Data source registration failed in the query engine. "
                "Please retry. If the issue continues, contact support."
            ),
        ) from exc
    finally:
        await reg.aclose()

    ds.status = "active"
    await session.commit()
    await session.refresh(ds)

    # Auto-create a saved query named after this data source (when attached to a
    # project). Best-effort: never fail source creation if query creation errors.
    if ds.project_id is not None:
        try:
            from app.services.auto_query import ensure_datasource_query

            col_names = [c["name"] for c in columns if c.get("name")]
            await ensure_datasource_query(
                session,
                project_id=ds.project_id,
                owner_id=context.user_id,
                display_name=ds.display_name,
                view_name=view_name,
                columns=col_names,
            )
            await session.commit()
        except Exception as exc:  # non-fatal
            logger.warning(
                "Auto-create query for %s failed (non-fatal): %s",
                view_name,
                exc,
            )
            await session.rollback()

    return ds.to_dict()


@router.get("")
async def list_database_sources(
    project_id: int | None = None,
    include_archived: bool = False,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[dict]:
    stmt = select(DatabaseDataSource).where(
        DatabaseDataSource.tenant_id == context.tenant_id
    )
    if project_id is not None:
        stmt = stmt.where(DatabaseDataSource.project_id == project_id)
    else:
        stmt = stmt.where(DatabaseDataSource.created_by == context.user_id)
    if not include_archived:
        stmt = stmt.where(DatabaseDataSource.archived.is_(False))
    rows = (await session.scalars(stmt)).all()
    return [r.to_dict() for r in rows]


async def find_query_dependencies(
    session: AsyncSession, *, tenant_id: int, view_name: str
) -> list[dict]:
    """Return active saved queries that reference ``view_name`` as a datasource.

    A query depends on the source if it joins/selects it directly
    (``left_datasource``/``right_datasource``) or names it in its SQL text.
    """
    from app.models.project import Project as _Project
    from app.models.saved_query import SavedQuery as _SavedQuery

    rows = (
        await session.scalars(
            select(_SavedQuery)
            .join(_Project, _SavedQuery.project_id == _Project.id)
            .where(_Project.tenant_id == tenant_id)
        )
    ).all()
    deps: list[dict] = []
    for q in rows:
        sql = q.sql_text or ""
        if (
            q.left_datasource == view_name
            or q.right_datasource == view_name
            or f'"{view_name}"' in sql
        ):
            deps.append({"id": q.id, "name": q.name})
    return deps


@router.patch("/{source_id}/archive")
async def archive_database_source(
    source_id: int,
    body: ArchiveSourceRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict:
    """Archive (hide) or unarchive a data source without deleting it."""
    ds = await session.get(DatabaseDataSource, source_id)
    if ds is None or ds.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Data source not found")
    if ds.created_by != context.user_id and context.role != "admin":
        raise HTTPException(status_code=403, detail="Not allowed to modify this source")
    ds.archived = body.archived
    ds.archived_at = datetime.now(UTC) if body.archived else None
    await session.commit()
    await session.refresh(ds)
    return ds.to_dict()


@router.delete("/{source_id}")
async def delete_database_source(
    source_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict:
    ds = await session.get(DatabaseDataSource, source_id)
    if ds is None or ds.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Data source not found")
    if ds.created_by != context.user_id and context.role != "admin":
        raise HTTPException(status_code=403, detail="Not allowed to delete this source")
    if not ds.archived:
        raise HTTPException(
            status_code=409,
            detail="Archive the data source before deleting it.",
        )
    deps = await find_query_dependencies(
        session, tenant_id=context.tenant_id, view_name=ds.teiid_view_name
    )
    if deps:
        names = ", ".join(d["name"] for d in deps)
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete: {len(deps)} active quer"
            f"{'y' if len(deps) == 1 else 'ies'} depend on this source ({names}).",
        )
    # Remove Teiid view and foreign table (best-effort)
    try:
        endpoint = await TenantTeiidResolver(session).resolve_for_org(context.tenant_id)
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0)
        ) as teiid_client:
            teiid_resp = await teiid_client.post(
                f"{endpoint.servlet_url}/TeiidExcelImporterTest/deleteDataSource",
                data={"dataSourceName": ds.teiid_view_name},
            )
            if teiid_resp.status_code == 200:
                logger.info("Teiid view/foreign-table removed for %s", ds.teiid_view_name)
            else:
                logger.warning(
                    "Teiid deleteDataSource returned %s for %s: %s",
                    teiid_resp.status_code, ds.teiid_view_name, teiid_resp.text,
                )
    except Exception as exc:
        logger.warning("Failed to clean up Teiid for %s: %s", ds.teiid_view_name, exc)

    await session.delete(ds)
    await session.commit()
    return {"status": "deleted", "id": source_id}


@router.get("/{source_id}/preflight-delete")
async def preflight_delete_database_source(
    source_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict:
    """Return whether a database data source can be permanently deleted."""
    ds = await session.get(DatabaseDataSource, source_id)
    if ds is None or ds.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Data source not found")

    blockers: list[dict[str, str]] = []
    if not ds.archived:
        blockers.append({
            "category": "not_archived",
            "message": "Archive the data source before deleting it.",
        })

    deps = await find_query_dependencies(
        session, tenant_id=context.tenant_id, view_name=ds.teiid_view_name
    )
    if deps:
        blockers.append({
            "category": "active_dependencies",
            "message": f"{len(deps)} active saved quer{'y' if len(deps) == 1 else 'ies'} depend on this source.",
        })

    return {
        "id": source_id,
        "safe": len(blockers) == 0 and ds.archived,
        "archived": ds.archived,
        "blockers": blockers,
        "active_query_dependencies": deps,
    }


@router.post("/reconcile")
async def reconcile_sources(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.ADMIN)),
) -> dict:
    """Re-register all active DB-table sources' datasources/models in Teiid.

    Runtime JDBC datasources do not survive a Teiid restart, so this restores
    every DB-table source after a Teiid container restart/recreate.  Admin-only;
    also invoked automatically on platform-api startup.
    """
    return await reconcile_database_sources(session)