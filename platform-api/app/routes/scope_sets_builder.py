"""Scope Relationship Builder routes.

The builder loads/saves a scope set's full canvas map (table positions +
relationship lines), lists the saved queries draggable onto the canvas, and
serves AI-suggested field-to-field relationships.

Drill-down filtering itself is unchanged — it still runs through
``/api/query-scopes/filter`` keyed by saved-query id.
"""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.query_scope import QueryScope
from app.models.saved_query import SavedQuery
from app.models.scope_canvas_layout import ScopeCanvasLayout
from app.routes.scope_sets_crud import _get_project, _get_scope_set, _scope_count
from app.schemas.scope_set import (
    ScopeAISuggestion,
    ScopeAISuggestRequest,
    ScopeAISuggestResponse,
    ScopeBuilderTable,
    ScopeCanvasTable,
    ScopeMapRead,
    ScopeMapSave,
    ScopeRelationship,
    ScopeSetRead,
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

    Runs the LLM-based directional analyzer (the same Phase 1 AI call + Phase 2
    cell validation that powers "Generate AI Scopes") over the selected saved
    queries and returns the validated suggestions — one direction per pair
    (summarized/aggregated → detailed/raw), never the reverse — for the user to
    accept onto the canvas.
    """
    scope_set = await _get_scope_set(
        session, scope_set_id=scope_set_id, tenant_id=context.tenant_id
    )
    if not payload.query_ids:
        return ScopeAISuggestResponse(suggestions=[])

    # Reuse the shared analyzer from the generate path. Imported lazily to keep
    # the scope_sets ↔ ai_proxy module graph acyclic.
    from app.routes.ai_proxy import _analyze_project_scopes

    validated, _names = await _analyze_project_scopes(
        session=session,
        context=context,
        project_id=scope_set.project_id,
        query_ids=payload.query_ids,
    )

    suggestions: list[ScopeAISuggestion] = [
        ScopeAISuggestion(
            query_id=s["source_query_id"],
            source_field=s["source_field"],
            source_table=s.get("source_query_name"),
            target_query_id=s["target_query_id"],
            target_field=s["target_field"],
            target_table=s.get("target_query_name"),
            match_group_id=None,
            match_mode="all",
            confidence_score=s.get("confidence"),
            rationale=(
                s.get("reason")
                or "AI-suggested drill-down "
                f"({s.get('source_query_name')} → {s.get('target_query_name')})."
            ),
        )
        for s in validated
    ]
    return ScopeAISuggestResponse(suggestions=suggestions)
