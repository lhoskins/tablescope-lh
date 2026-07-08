"""Scope set + Scope Relationship Builder routes.

A *scope set* is a named, toggleable parent of :class:`QueryScope` field
mappings.  The Scope Navigation page lists sets; the Scope Relationship Builder
loads/saves a set's full canvas map (table positions + relationship lines).

Drill-down filtering itself is unchanged — it still runs through
``/api/query-scopes/filter`` keyed by saved-query id.  These routes only manage
how scopes are grouped, positioned, and toggled.
"""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, has_role, require_role
from app.database import get_db
from app.models.project import Project, ProjectMember
from app.models.query_scope import QueryScope
from app.models.saved_query import SavedQuery
from app.models.scope_canvas_layout import ScopeCanvasLayout
from app.models.scope_set import ScopeSet
from app.models.user import User
from app.schemas.scope_set import (
    ScopeAISuggestion,
    ScopeAISuggestRequest,
    ScopeAISuggestResponse,
    ScopeBuilderTable,
    ScopeCanvasTable,
    ScopeMapRead,
    ScopeMapSave,
    ScopeRelationship,
    ScopeSetCreate,
    ScopeSetRead,
    ScopeSetUpdate,
)
from app.services.auto_scope import extract_select_columns

router = APIRouter(tags=["scope-sets"])

logger = logging.getLogger(__name__)

_FIELD_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_$. ]*$")
_STAR_RE = re.compile(r"\bSELECT\s+(.*?)\s+FROM\s+", re.IGNORECASE | re.DOTALL)


def _select_has_star(sql: str) -> bool:
    """True when the SELECT clause uses ``*`` (so static parsing is incomplete)."""
    m = _STAR_RE.search(sql or "")
    if m is None:
        return False
    return "*" in m.group(1)


async def _resolve_query_fields(
    session: AsyncSession,
    *,
    context: RequestContext,
    project_id: int,
    query_sql: str | None,
) -> list[str]:
    """Return a query's output columns.

    Static parsing of the SELECT clause works for explicit column lists.  For
    ``SELECT *`` (and ``t.*``) the column names are not in the SQL text, so we
    execute the query through Teiid (1-row probe) and read the result columns.
    """
    sql = (query_sql or "").strip()
    if not sql:
        return []
    cols = extract_select_columns(sql)
    if cols and not _select_has_star(sql):
        return cols
    # Star query (or unparseable) — resolve actual columns from Teiid.
    try:
        from app.routes.query import _resolve_vdb_database, _run_sql
        from app.services.tenant_teiid_resolver import TenantTeiidResolver

        database = await _resolve_vdb_database(
            session=session, context=context, project_id=project_id
        )
        endpoint = await TenantTeiidResolver(session).resolve_for_org(
            context.tenant_id
        )
        probe = f"SELECT * FROM ({sql.rstrip(';')}) AS __scope_cols LIMIT 1"
        result = await _run_sql(
            database=database,
            sql=probe,
            teiid_host=endpoint.pg_host,
            teiid_port=endpoint.pg_port,
        )
        resolved = list(result.get("columns") or [])
        if resolved:
            return resolved
    except Exception as exc:  # degrade gracefully to static columns
        logger.warning(
            "Could not resolve columns for star query in project %d: %s",
            project_id,
            exc,
        )
    return cols


async def _get_project(
    session: AsyncSession, *, project_id: int, tenant_id: int
) -> Project:
    project = await session.get(Project, project_id)
    if project is None or project.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _get_scope_set(
    session: AsyncSession, *, scope_set_id: int, tenant_id: int
) -> ScopeSet:
    scope_set = await session.get(ScopeSet, scope_set_id)
    if scope_set is None or scope_set.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Scope set not found")
    return scope_set


async def _scope_count(session: AsyncSession, scope_set_id: int) -> int:
    return int(
        await session.scalar(
            select(func.count(QueryScope.id)).where(
                QueryScope.scope_set_id == scope_set_id
            )
        )
        or 0
    )


async def _is_project_admin(
    session: AsyncSession, *, project_id: int, context: RequestContext
) -> bool:
    """True when the user is a tenant admin, project owner, or project-admin member."""
    if context.is_service or has_role(context.role, Role.ADMIN):
        return True
    project = await session.get(Project, project_id)
    if project is not None and project.owner_id == context.user_id:
        return True
    member = await session.get(
        ProjectMember, {"project_id": project_id, "user_id": context.user_id}
    )
    return bool(
        member is not None
        and member.is_active
        and member.role in ("admin", "owner")
    )


async def _can_delete_scope_set(
    session: AsyncSession, *, scope_set: ScopeSet, context: RequestContext
) -> bool:
    """A scope set can be deleted by its creator or a project admin."""
    if scope_set.created_by is not None and scope_set.created_by == context.user_id:
        return True
    return await _is_project_admin(
        session, project_id=scope_set.project_id, context=context
    )


async def _scope_set_dict(
    session: AsyncSession,
    scope_set: ScopeSet,
    scope_count: int,
    context: RequestContext,
) -> dict:
    """Build a ScopeSetRead dict for a single set incl. creator + permission."""
    creators = await _creator_info(session, [scope_set])
    name, email = creators.get(scope_set.created_by or -1, (None, None))
    can_delete = await _can_delete_scope_set(
        session, scope_set=scope_set, context=context
    )
    return scope_set.to_dict(
        scope_count=scope_count,
        creator_name=name,
        creator_email=email,
        can_delete=can_delete,
    )


async def _creator_info(
    session: AsyncSession, scope_sets: list[ScopeSet]
) -> dict[int, tuple[str | None, str | None]]:
    """Map user id -> (display name, email) for the given scope sets' creators."""
    ids = {s.created_by for s in scope_sets if s.created_by is not None}
    if not ids:
        return {}
    users = (
        await session.scalars(select(User).where(User.id.in_(ids)))
    ).all()
    out: dict[int, tuple[str | None, str | None]] = {}
    for u in users:
        name = u.display_name or " ".join(
            p for p in (u.first_name, u.last_name) if p
        ).strip()
        out[u.id] = (name or None, u.email)
    return out


# ── Scope Navigation: list / create ──────────────────────────────────────


@router.get(
    "/projects/{project_id}/scope_sets", response_model=list[ScopeSetRead]
)
async def list_scope_sets(
    project_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[ScopeSetRead]:
    await _get_project(session, project_id=project_id, tenant_id=context.tenant_id)
    sets = (
        await session.scalars(
            select(ScopeSet)
            .where(
                ScopeSet.tenant_id == context.tenant_id,
                ScopeSet.project_id == project_id,
            )
            .order_by(ScopeSet.created_at.asc())
        )
    ).all()
    creators = await _creator_info(session, list(sets))
    project_admin = await _is_project_admin(
        session, project_id=project_id, context=context
    )
    out: list[ScopeSetRead] = []
    for s in sets:
        count = await _scope_count(session, s.id)
        name, email = creators.get(s.created_by or -1, (None, None))
        can_delete = project_admin or (
            s.created_by is not None and s.created_by == context.user_id
        )
        out.append(
            ScopeSetRead.model_validate(
                s.to_dict(
                    scope_count=count,
                    creator_name=name,
                    creator_email=email,
                    can_delete=can_delete,
                )
            )
        )
    return out


@router.post(
    "/projects/{project_id}/scope_sets",
    response_model=ScopeSetRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_scope_set(
    project_id: int,
    payload: ScopeSetCreate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> ScopeSetRead:
    await _get_project(session, project_id=project_id, tenant_id=context.tenant_id)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Scope set name is required")
    set_type = payload.type if payload.type in ("ai_generated", "manual") else "manual"
    scope_set = ScopeSet(
        tenant_id=context.tenant_id,
        project_id=project_id,
        name=name,
        description=payload.description,
        type=set_type,
        enabled=True,
        created_by=context.user_id,
    )
    session.add(scope_set)
    await session.commit()
    await session.refresh(scope_set)
    return ScopeSetRead.model_validate(
        await _scope_set_dict(session, scope_set, 0, context)
    )


# ── Scope Builder: available tables ──────────────────────────────────────


@router.get(
    "/projects/{project_id}/scope-builder/tables",
    response_model=list[ScopeBuilderTable],
)
async def list_scope_builder_tables(
    project_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[ScopeBuilderTable]:
    """Saved queries in the project + their fields, draggable to the canvas."""
    await _get_project(session, project_id=project_id, tenant_id=context.tenant_id)
    queries = (
        await session.scalars(
            select(SavedQuery)
            .where(SavedQuery.project_id == project_id)
            .order_by(SavedQuery.name.asc())
        )
    ).all()
    tables: list[ScopeBuilderTable] = []
    for q in queries:
        fields = await _resolve_query_fields(
            session,
            context=context,
            project_id=project_id,
            query_sql=q.sql_text,
        )
        tables.append(
            ScopeBuilderTable(
                table_key=f"query:{q.id}",
                table_name=q.name,
                query_id=q.id,
                fields=fields,
            )
        )
    return tables


# ── Scope set: read / update / delete ────────────────────────────────────


@router.get("/scope_sets/{scope_set_id}", response_model=ScopeSetRead)
async def get_scope_set(
    scope_set_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> ScopeSetRead:
    scope_set = await _get_scope_set(
        session, scope_set_id=scope_set_id, tenant_id=context.tenant_id
    )
    count = await _scope_count(session, scope_set.id)
    return ScopeSetRead.model_validate(
        await _scope_set_dict(session, scope_set, count, context)
    )


@router.patch("/scope_sets/{scope_set_id}", response_model=ScopeSetRead)
async def update_scope_set(
    scope_set_id: int,
    payload: ScopeSetUpdate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> ScopeSetRead:
    scope_set = await _get_scope_set(
        session, scope_set_id=scope_set_id, tenant_id=context.tenant_id
    )
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Name cannot be empty")
        scope_set.name = name
    if payload.description is not None:
        scope_set.description = payload.description
    if payload.enabled is not None:
        scope_set.enabled = payload.enabled
        # Toggling the set toggles every mapping it owns so drill-down respects it.
        scopes = await session.scalars(
            select(QueryScope).where(QueryScope.scope_set_id == scope_set.id)
        )
        for sc in scopes:
            sc.enabled = payload.enabled
    await session.commit()
    await session.refresh(scope_set)
    count = await _scope_count(session, scope_set.id)
    return ScopeSetRead.model_validate(
        await _scope_set_dict(session, scope_set, count, context)
    )


@router.delete(
    "/scope_sets/{scope_set_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_scope_set(
    scope_set_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> Response:
    scope_set = await _get_scope_set(
        session, scope_set_id=scope_set_id, tenant_id=context.tenant_id
    )
    if not await _can_delete_scope_set(
        session, scope_set=scope_set, context=context
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the scope creator or a project admin can delete this scope.",
        )
    # Explicitly remove children (SQLite test DB does not enforce FK cascade).
    for layout in await session.scalars(
        select(ScopeCanvasLayout).where(
            ScopeCanvasLayout.scope_set_id == scope_set.id
        )
    ):
        await session.delete(layout)
    for sc in await session.scalars(
        select(QueryScope).where(QueryScope.scope_set_id == scope_set.id)
    ):
        await session.delete(sc)
    await session.delete(scope_set)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/scope_sets/{scope_set_id}/scopes", response_model=list[ScopeRelationship]
)
async def list_scope_set_scopes(
    scope_set_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[ScopeRelationship]:
    await _get_scope_set(
        session, scope_set_id=scope_set_id, tenant_id=context.tenant_id
    )
    scopes = (
        await session.scalars(
            select(QueryScope).where(QueryScope.scope_set_id == scope_set_id)
        )
    ).all()
    return [ScopeRelationship.model_validate(s.to_dict()) for s in scopes]


# ── Scope Relationship Builder: load / save map ──────────────────────────


@router.get("/scope_sets/{scope_set_id}/map", response_model=ScopeMapRead)
async def get_scope_map(
    scope_set_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> ScopeMapRead:
    scope_set = await _get_scope_set(
        session, scope_set_id=scope_set_id, tenant_id=context.tenant_id
    )
    count = await _scope_count(session, scope_set.id)
    layouts = (
        await session.scalars(
            select(ScopeCanvasLayout).where(
                ScopeCanvasLayout.scope_set_id == scope_set_id
            )
        )
    ).all()
    scopes = (
        await session.scalars(
            select(QueryScope).where(QueryScope.scope_set_id == scope_set_id)
        )
    ).all()
    return ScopeMapRead(
        scope_set=ScopeSetRead.model_validate(
            scope_set.to_dict(scope_count=count)
        ),
        tables=[ScopeCanvasTable.model_validate(layout.to_dict()) for layout in layouts],
        relationships=[
            ScopeRelationship.model_validate(s.to_dict()) for s in scopes
        ],
    )


@router.put("/scope_sets/{scope_set_id}/map", response_model=ScopeMapRead)
async def save_scope_map(
    scope_set_id: int,
    payload: ScopeMapSave,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> ScopeMapRead:
    """Replace the scope set's canvas tables + relationship lines wholesale."""
    scope_set = await _get_scope_set(
        session, scope_set_id=scope_set_id, tenant_id=context.tenant_id
    )

    if payload.name is not None:
        name = payload.name.strip()
        if name:
            scope_set.name = name
    if payload.description is not None:
        scope_set.description = payload.description
    if payload.enabled is not None:
        scope_set.enabled = payload.enabled

    # Validate referenced queries belong to this project before mutating.
    referenced_ids = {t.query_id for t in payload.tables if t.query_id is not None}
    for rel in payload.relationships:
        referenced_ids.add(rel.query_id)
        referenced_ids.add(rel.target_query_id)
    if referenced_ids:
        valid = set(
            (
                await session.scalars(
                    select(SavedQuery.id).where(
                        SavedQuery.id.in_(referenced_ids),
                        SavedQuery.project_id == scope_set.project_id,
                    )
                )
            ).all()
        )
        missing = referenced_ids - valid
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Queries not in project: {sorted(missing)}",
            )

    # Wipe + rewrite canvas layout.
    for layout in await session.scalars(
        select(ScopeCanvasLayout).where(
            ScopeCanvasLayout.scope_set_id == scope_set_id
        )
    ):
        await session.delete(layout)
    for t in payload.tables:
        session.add(
            ScopeCanvasLayout(
                scope_set_id=scope_set_id,
                table_key=t.table_key,
                table_name=t.table_name,
                query_id=t.query_id,
                datasource_id=t.datasource_id,
                x_position=t.x_position,
                y_position=t.y_position,
                width=t.width,
                height=t.height,
            )
        )

    # Wipe + rewrite relationship lines.
    for sc in await session.scalars(
        select(QueryScope).where(QueryScope.scope_set_id == scope_set_id)
    ):
        await session.delete(sc)
    await session.flush()

    seen_rel: set[tuple[int, str, int, str]] = set()
    for rel in payload.relationships:
        # Dedupe identical mappings within the payload (the per-set unique
        # constraint would otherwise reject the second one).
        rel_key = (rel.query_id, rel.source_field, rel.target_query_id, rel.target_field)
        if rel_key in seen_rel:
            continue
        seen_rel.add(rel_key)
        if not _FIELD_RE.match(rel.source_field):
            raise HTTPException(
                status_code=400, detail=f"Invalid source field: {rel.source_field}"
            )
        if not _FIELD_RE.match(rel.target_field):
            raise HTTPException(
                status_code=400, detail=f"Invalid target field: {rel.target_field}"
            )
        match_mode = rel.match_mode if rel.match_mode in ("all", "any") else "all"
        direction = (
            rel.direction
            if rel.direction in ("source_to_target", "target_to_source")
            else "source_to_target"
        )
        session.add(
            QueryScope(
                tenant_id=context.tenant_id,
                project_id=scope_set.project_id,
                scope_set_id=scope_set_id,
                query_id=rel.query_id,
                source_field=rel.source_field,
                source_table=rel.source_table,
                target_query_id=rel.target_query_id,
                target_field=rel.target_field,
                target_table=rel.target_table,
                direction=direction,
                match_group_id=rel.match_group_id,
                match_mode=match_mode,
                enabled=rel.enabled and scope_set.enabled,
                confidence_score=rel.confidence_score,
                created_by_ai=rel.created_by_ai,
                created_by=context.user_id,
            )
        )

    await session.commit()
    return await get_scope_map(
        scope_set_id=scope_set_id, session=session, context=context
    )


# ── AI Suggest ───────────────────────────────────────────────────────────


@router.post(
    "/scope_sets/{scope_set_id}/ai-suggest",
    response_model=ScopeAISuggestResponse,
)
async def ai_suggest_scopes(
    scope_set_id: int,
    payload: ScopeAISuggestRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> ScopeAISuggestResponse:
    """Suggest field-to-field relationships among the canvas tables.

    Matches identically-named columns across the selected saved queries (the
    same heuristic that powers automatic scope creation) and returns them as
    suggestions the user can accept onto the canvas.
    """
    scope_set = await _get_scope_set(
        session, scope_set_id=scope_set_id, tenant_id=context.tenant_id
    )
    if not payload.query_ids:
        return ScopeAISuggestResponse(suggestions=[])

    queries = (
        await session.scalars(
            select(SavedQuery).where(
                SavedQuery.id.in_(payload.query_ids),
                SavedQuery.project_id == scope_set.project_id,
            )
        )
    ).all()
    cols_by_q: dict[int, dict[str, str]] = {}
    name_by_q: dict[int, str] = {}
    for q in queries:
        name_by_q[q.id] = q.name
        fields = await _resolve_query_fields(
            session,
            context=context,
            project_id=scope_set.project_id,
            query_sql=q.sql_text,
        )
        cols_by_q[q.id] = {c.lower(): c for c in fields}

    suggestions: list[ScopeAISuggestion] = []
    seen: set[tuple[int, str, int, str]] = set()
    ids = sorted(cols_by_q.keys())
    for i, qa in enumerate(ids):
        for qb in ids[i + 1 :]:
            common = set(cols_by_q[qa]) & set(cols_by_q[qb])
            for low in sorted(common):
                src_field = cols_by_q[qa][low]
                tgt_field = cols_by_q[qb][low]
                key = (qa, src_field, qb, tgt_field)
                if key in seen:
                    continue
                seen.add(key)
                # ID-like joins score higher than incidental shared names.
                score = 0.9 if low.endswith("id") else 0.6
                suggestions.append(
                    ScopeAISuggestion(
                        query_id=qa,
                        source_field=src_field,
                        source_table=name_by_q.get(qa),
                        target_query_id=qb,
                        target_field=tgt_field,
                        target_table=name_by_q.get(qb),
                        match_group_id=None,
                        match_mode="all",
                        confidence_score=score,
                        rationale=f"Both queries expose a '{src_field}' column.",
                    )
                )
    return ScopeAISuggestResponse(suggestions=suggestions)
