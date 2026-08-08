"""Saved queries owned by a project.

Split from ``projects.py``; see ``projects_shared.py`` for the helper cluster.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.dashboard import Dashboard
from app.models.project import Project
from app.models.query_scope import QueryScope
from app.models.saved_query import SavedQuery
from app.models.scope_set import ScopeSet
from app.models.user import User
from app.routes.projects_shared import _query_origin, _user_label
from app.schemas.project import (
    SavedQueryCreate,
    SavedQueryRead,
    SavedQueryUpdate,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("/{project_id}/queries", response_model=list[SavedQueryRead])
async def list_saved_queries(
    project_id: int,
    include_archived: bool = Query(default=False),
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[SavedQueryRead]:
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")
    stmt = select(SavedQuery).where(SavedQuery.project_id == project_id)
    if not include_archived:
        stmt = stmt.where(SavedQuery.is_archived.is_(False))
    rows = list(
        await session.scalars(stmt.order_by(SavedQuery.created_at.desc()))
    )

    # Owner names for the "Owner" column.
    users = list(
        await session.scalars(
            select(User).where(User.tenant_id == context.tenant_id)
        )
    )
    user_names = {u.id: _user_label(u) for u in users}

    # Active-scope participation: an enabled scope whose parent set is enabled
    # (or has no parent set) AND that has a target table. Only the *source* of
    # such a scope gets the scope icon (outgoing); a table that is only a
    # target has an incoming scope but no icon.
    scope_rows = (
        await session.execute(
            select(QueryScope.query_id, QueryScope.target_query_id)
            .outerjoin(ScopeSet, QueryScope.scope_set_id == ScopeSet.id)
            .where(
                QueryScope.project_id == project_id,
                QueryScope.enabled.is_(True),
                QueryScope.target_query_id.is_not(None),
                or_(
                    QueryScope.scope_set_id.is_(None),
                    ScopeSet.enabled.is_(True),
                ),
            )
        )
    ).all()
    outgoing_counts: dict[int, int] = {}
    incoming_counts: dict[int, int] = {}
    for source_id, target_id in scope_rows:
        if source_id is not None:
            outgoing_counts[source_id] = outgoing_counts.get(source_id, 0) + 1
        if target_id is not None:
            incoming_counts[target_id] = incoming_counts.get(target_id, 0) + 1

    results: list[SavedQueryRead] = []
    for q in rows:
        read = SavedQueryRead.model_validate(q)
        read.owner_name = (
            user_names.get(q.owner_id) if q.owner_id is not None else None
        )
        read.origin, read.origin_label = _query_origin(q)
        read.source_name = q.left_datasource or (
            "AI Generated" if q.ai_generated else None
        )
        outgoing = outgoing_counts.get(q.id, 0)
        incoming = incoming_counts.get(q.id, 0)
        read.outgoing_scope_count = outgoing
        read.has_outgoing_scope = outgoing > 0
        read.incoming_scope_count = incoming
        read.has_incoming_scope = incoming > 0
        # Backward-compat aggregate.
        read.active_scope_count = outgoing + incoming
        read.has_active_scope = read.active_scope_count > 0
        results.append(read)
    return results


async def _maybe_autoscope_on_save(
    session: AsyncSession,
    *,
    query: SavedQuery,
    context: RequestContext,
) -> None:
    """Refresh AI drill-down scopes after a query is saved.

    Only runs when the project already has an *enabled* "AI Generated Scopes"
    set — i.e. the user has opted into autoscoping via the Scopes page toggle.
    This keeps that set fresh as new queries are added without forcing AI
    scopes onto projects that never enabled them. Fail-soft: a scoping error
    must never break saving the query.
    """
    try:
        ai_set = await session.scalar(
            select(ScopeSet).where(
                ScopeSet.tenant_id == context.tenant_id,
                ScopeSet.project_id == query.project_id,
                ScopeSet.type == "ai_generated",
                ScopeSet.enabled.is_(True),
            )
        )
        if ai_set is None:
            return
        from app.services.auto_scope import auto_create_scopes_for_query

        created = await auto_create_scopes_for_query(
            session,
            query=query,
            tenant_id=context.tenant_id,
            user_id=context.user_id or ai_set.created_by or 0,
        )
        if created:
            await session.commit()
    except Exception as exc:  # never break the save on a scoping error
        logger.warning(
            "Auto-scope on save failed for query %s: %s", query.id, exc
        )


@router.post("/{project_id}/queries", response_model=SavedQueryRead,
             status_code=status.HTTP_201_CREATED)
async def create_saved_query(
    project_id: int,
    payload: SavedQueryCreate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> SavedQueryRead:
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")
    query = SavedQuery(
        project_id=project_id,
        owner_id=context.user_id,
        name=payload.name,
        description=payload.description,
        left_datasource=payload.left_datasource,
        right_datasource=payload.right_datasource,
        join_type=payload.join_type,
        left_column=payload.left_column,
        right_column=payload.right_column,
        sql_text=payload.sql_text,
        ai_generated=payload.ai_generated,
        is_shared=payload.is_shared,
    )
    session.add(query)
    await session.commit()
    await session.refresh(query)
    await _maybe_autoscope_on_save(session, query=query, context=context)
    read = SavedQueryRead.model_validate(query)
    read.origin, read.origin_label = _query_origin(query)
    return read


@router.put("/{project_id}/queries/{query_id}", response_model=SavedQueryRead)
async def update_saved_query(
    project_id: int,
    query_id: int,
    payload: SavedQueryUpdate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> SavedQueryRead:
    query = await session.get(SavedQuery, query_id)
    if query is None or query.project_id != project_id:
        raise HTTPException(status_code=404, detail="Query not found")
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")

    if payload.name is not None:
        query.name = payload.name
    if payload.description is not None:
        query.description = payload.description
    if payload.left_datasource is not None:
        query.left_datasource = payload.left_datasource
    if payload.right_datasource is not None:
        query.right_datasource = payload.right_datasource
    if payload.join_type is not None:
        query.join_type = payload.join_type
    if payload.left_column is not None:
        query.left_column = payload.left_column
    if payload.right_column is not None:
        query.right_column = payload.right_column
    if payload.sql_text is not None:
        query.sql_text = payload.sql_text
    if payload.ai_generated is not None:
        query.ai_generated = payload.ai_generated
    if payload.is_shared is not None:
        query.is_shared = payload.is_shared

    await session.commit()
    await session.refresh(query)
    await _maybe_autoscope_on_save(session, query=query, context=context)
    read = SavedQueryRead.model_validate(query)
    read.origin, read.origin_label = _query_origin(query)
    return read


@router.post(
    "/{project_id}/queries/{query_id}/archive",
    response_model=SavedQueryRead,
)
async def archive_saved_query(
    project_id: int,
    query_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> SavedQueryRead:
    """Archive a query. It stays executable but is hidden from normal lists."""
    query = await session.get(SavedQuery, query_id)
    if query is None or query.project_id != project_id:
        raise HTTPException(status_code=404, detail="Query not found")
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")
    query.is_archived = True
    query.archived_at = datetime.now(UTC)
    query.archived_by = context.user_id
    await session.commit()
    await session.refresh(query)
    read = SavedQueryRead.model_validate(query)
    read.origin, read.origin_label = _query_origin(query)
    return read


@router.post(
    "/{project_id}/queries/{query_id}/restore",
    response_model=SavedQueryRead,
)
async def restore_saved_query(
    project_id: int,
    query_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> SavedQueryRead:
    """Restore an archived query back to the active list."""
    query = await session.get(SavedQuery, query_id)
    if query is None or query.project_id != project_id:
        raise HTTPException(status_code=404, detail="Query not found")
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")
    query.is_archived = False
    query.archived_at = None
    query.archived_by = None
    await session.commit()
    await session.refresh(query)
    read = SavedQueryRead.model_validate(query)
    read.origin, read.origin_label = _query_origin(query)
    return read


async def _query_dependencies(
    session: AsyncSession, query: SavedQuery
) -> dict[str, Any]:
    """Blocking dependencies for a saved query.

    Delete is refused while any exist. Returns per-kind counts plus an
    ``items`` list of ``{"type", "name"}`` descriptors so the caller can render
    a specific dependency warning (e.g. "Dashboard: Executive KPI Dashboard").
    """
    items: list[dict[str, str]] = []

    # Scopes: this query feeds another (source) or is fed by another (target).
    # Name each by the counterpart table on the scope so the warning is concrete.
    source_scopes = list(
        await session.scalars(
            select(QueryScope).where(QueryScope.query_id == query.id)
        )
    )
    target_scopes = list(
        await session.scalars(
            select(QueryScope).where(QueryScope.target_query_id == query.id)
        )
    )
    for sc in source_scopes:
        items.append({
            "type": "Scope",
            "name": f"→ {sc.target_table or 'linked table'}",
        })
    for sc in target_scopes:
        items.append({
            "type": "Scope",
            "name": f"{sc.source_table or 'linked table'} →",
        })

    # Dashboards whose widget config references this query id.
    dashboards = list(
        await session.scalars(
            select(Dashboard).where(Dashboard.project_id == query.project_id)
        )
    )
    dashboard_refs = 0
    for dash in dashboards:
        config = dash.config if isinstance(dash.config, dict) else {}
        widgets = config.get("widgets")
        if not isinstance(widgets, list):
            continue
        for widget in widgets:
            if not isinstance(widget, dict):
                continue
            source = widget.get("dataSource")
            if (
                isinstance(source, dict)
                and source.get("kind") == "query"
                and source.get("queryId") == query.id
            ):
                dashboard_refs += 1
                items.append({"type": "Dashboard", "name": dash.name})
                break

    return {
        "dashboards": dashboard_refs,
        "scopes_source": len(source_scopes),
        "scopes_target": len(target_scopes),
        "items": items,
    }


@router.delete("/{project_id}/queries/{query_id}")
async def delete_saved_query(
    project_id: int,
    query_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> Response:
    query = await session.get(SavedQuery, query_id)
    if query is None or query.project_id != project_id:
        raise HTTPException(status_code=404, detail="Query not found")
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")

    # A query can only be permanently deleted once archived.
    if not query.is_archived:
        raise HTTPException(
            status_code=409,
            detail="Query must be archived before it can be deleted.",
        )

    # And only when it has no remaining dependencies.
    deps = await _query_dependencies(session, query)
    items: list[dict[str, str]] = deps["items"]
    if items:
        named = "; ".join(f"{d['type']}: {d['name']}" for d in items)
        raise HTTPException(
            status_code=409,
            detail=(
                "Cannot delete this query — remove these dependencies first: "
                + named
            ),
        )

    await session.delete(query)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

