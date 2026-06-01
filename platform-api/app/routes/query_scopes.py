"""Query scope (drill-down) routes — keyed by saved-query id.

Provides CRUD over :class:`QueryScope` plus a ``/filter`` drill-down endpoint
that executes the target query filtered by a clicked cell value.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.project import Project
from app.models.query_scope import QueryScope
from app.models.saved_query import SavedQuery
from app.routes.query import _resolve_vdb_database, _run_sql
from app.schemas.query_scope import (
    QueryScopeCreate,
    QueryScopeFilterRequest,
    QueryScopeFilterResponse,
    QueryScopeRead,
)

router = APIRouter(prefix="/query-scopes", tags=["query-scopes"])

_FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$. ]*$")


async def _get_project_for_query(
    session: AsyncSession, *, query_id: int, tenant_id: int
) -> tuple[SavedQuery, Project]:
    query = await session.get(SavedQuery, query_id)
    if query is None:
        raise HTTPException(status_code=404, detail="Query not found")
    project = await session.get(Project, query.project_id)
    if project is None or project.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return query, project


@router.get("", response_model=list[QueryScopeRead])
async def list_query_scopes(
    query_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[QueryScopeRead]:
    """List scopes whose *source* is the given query."""
    await _get_project_for_query(session, query_id=query_id, tenant_id=context.tenant_id)
    rows = await session.scalars(
        select(QueryScope).where(
            QueryScope.tenant_id == context.tenant_id,
            QueryScope.query_id == query_id,
        )
    )
    return [QueryScopeRead.model_validate(s.to_dict()) for s in rows]


@router.post("", response_model=QueryScopeRead, status_code=status.HTTP_201_CREATED)
async def create_query_scope(
    payload: QueryScopeCreate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> QueryScopeRead:
    source_query, project = await _get_project_for_query(
        session, query_id=payload.query_id, tenant_id=context.tenant_id
    )
    target_query, _ = await _get_project_for_query(
        session, query_id=payload.target_query_id, tenant_id=context.tenant_id
    )
    if not _FIELD_RE.match(payload.source_field):
        raise HTTPException(status_code=400, detail="Invalid source field")
    if not _FIELD_RE.match(payload.target_field):
        raise HTTPException(status_code=400, detail="Invalid target field")

    existing = await session.scalar(
        select(QueryScope).where(
            QueryScope.query_id == payload.query_id,
            QueryScope.source_field == payload.source_field,
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="A scope already exists for this query field. Edit it instead.",
        )

    scope = QueryScope(
        tenant_id=context.tenant_id,
        project_id=source_query.project_id,
        query_id=payload.query_id,
        source_field=payload.source_field,
        target_query_id=payload.target_query_id,
        target_field=payload.target_field,
        created_by=context.user_id,
    )
    session.add(scope)
    await session.commit()
    await session.refresh(scope)
    return QueryScopeRead.model_validate(scope.to_dict())


@router.patch("/{scope_id}", response_model=QueryScopeRead)
async def update_query_scope(
    scope_id: int,
    payload: QueryScopeCreate | None = None,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> QueryScopeRead:
    scope = await session.get(QueryScope, scope_id)
    if scope is None or scope.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Scope not found")
    if payload is None:
        raise HTTPException(status_code=400, detail="Missing body")
    await _get_project_for_query(
        session, query_id=payload.target_query_id, tenant_id=context.tenant_id
    )
    if not _FIELD_RE.match(payload.target_field):
        raise HTTPException(status_code=400, detail="Invalid target field")
    scope.target_query_id = payload.target_query_id
    scope.target_field = payload.target_field
    await session.commit()
    await session.refresh(scope)
    return QueryScopeRead.model_validate(scope.to_dict())


@router.delete("/{scope_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_query_scope(
    scope_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> Response:
    scope = await session.get(QueryScope, scope_id)
    if scope is None or scope.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Scope not found")
    await session.delete(scope)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _literal(value: Any) -> str:
    """Render a scalar value as a safe SQL literal."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int | float)):
        return str(value)
    text = str(value).replace("'", "''")
    return f"'{text}'"


@router.post("/filter", response_model=QueryScopeFilterResponse)
async def filter_by_scope(
    payload: QueryScopeFilterRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> QueryScopeFilterResponse:
    """Drill down: run the target query filtered by the clicked cell value."""
    scope = await session.get(QueryScope, payload.scope_id)
    if scope is None or scope.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Scope not found")

    target_query, project = await _get_project_for_query(
        session, query_id=scope.target_query_id, tenant_id=context.tenant_id
    )
    base_sql = (target_query.sql_text or "").strip().rstrip(";")
    if not base_sql:
        raise HTTPException(status_code=400, detail="Target query has no SQL")
    if not _FIELD_RE.match(scope.target_field):
        raise HTTPException(status_code=400, detail="Invalid target field")

    limit = max(1, min(payload.limit, 10_000))
    # Wrap the target query as a derived table so we can filter by the target
    # field on the *result* columns regardless of how the inner SQL is shaped.
    field = scope.target_field.split(".")[-1]
    wrapped = (
        f'SELECT * FROM ({base_sql}) AS scope_t '
        f'WHERE scope_t."{field}" = {_literal(payload.value)} '
        f"LIMIT {limit}"
    )

    database = await _resolve_vdb_database(
        session=session, context=context, project_id=project.id
    )
    result = await _run_sql(database=database, sql=wrapped)
    return QueryScopeFilterResponse(
        columns=result["columns"],
        rows=result["rows"],
        target_query_id=target_query.id,
        target_query_name=target_query.name,
        target_field=scope.target_field,
    )
