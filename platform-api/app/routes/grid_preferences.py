"""Grid preference routes — per-user column order + hidden columns per query.

Lets the result grid persist each user's column layout (ordering and which
columns are hidden) for a saved query, keyed by ``(user_id, query_id)``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.grid_preference import GridPreference
from app.models.project import Project
from app.models.saved_query import SavedQuery
from app.schemas.grid_preference import GridPreferenceRead, GridPreferenceWrite

router = APIRouter(prefix="/grid-preferences", tags=["grid-preferences"])


async def _check_query(session: AsyncSession, query_id: int, tenant_id: int) -> None:
    query = await session.get(SavedQuery, query_id)
    if query is None:
        raise HTTPException(status_code=404, detail="Query not found")
    project = await session.get(Project, query.project_id)
    if project is None or project.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")


@router.get("/{query_id}", response_model=GridPreferenceRead)
async def get_grid_preference(
    query_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> GridPreferenceRead:
    await _check_query(session, query_id, context.tenant_id)
    pref = (
        await session.scalars(
            select(GridPreference).where(
                GridPreference.user_id == context.user_id,
                GridPreference.query_id == query_id,
            )
        )
    ).first()
    if pref is None:
        return GridPreferenceRead(
            id=0, query_id=query_id, column_order=[], hidden_columns=[]
        )
    return GridPreferenceRead.model_validate(pref.to_dict())


@router.put("/{query_id}", response_model=GridPreferenceRead)
async def upsert_grid_preference(
    query_id: int,
    payload: GridPreferenceWrite,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> GridPreferenceRead:
    await _check_query(session, query_id, context.tenant_id)
    pref = (
        await session.scalars(
            select(GridPreference).where(
                GridPreference.user_id == context.user_id,
                GridPreference.query_id == query_id,
            )
        )
    ).first()
    if pref is None:
        pref = GridPreference(
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            query_id=query_id,
        )
        session.add(pref)
    pref.column_order = payload.column_order
    pref.hidden_columns = payload.hidden_columns
    await session.commit()
    await session.refresh(pref)
    return GridPreferenceRead.model_validate(pref.to_dict())
