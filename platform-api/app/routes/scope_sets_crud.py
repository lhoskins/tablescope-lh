"""Scope set CRUD routes.

A *scope set* is a named, toggleable parent of :class:`QueryScope` field
mappings. The Scope Navigation page lists sets; these routes create, read,
update, delete and enumerate them. Also hosts the lookup/permission helpers
shared with the Scope Relationship Builder routes.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, has_role, require_role
from app.database import get_db
from app.models.project import Project, ProjectMember
from app.models.query_scope import QueryScope
from app.models.scope_canvas_layout import ScopeCanvasLayout
from app.models.scope_set import ScopeSet
from app.models.user import User
from app.schemas.scope_set import (
    ScopeRelationship,
    ScopeSetCreate,
    ScopeSetRead,
    ScopeSetUpdate,
)

router = APIRouter(tags=["scope-sets"])

logger = logging.getLogger(__name__)


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


@router.post(
    "/projects/{project_id}/scope_sets/auto-generate",
    response_model=ScopeSetRead,
)
async def auto_generate_scope_set(
    project_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> ScopeSetRead:
    """Generate the project's "AI Generated Scopes" set on demand.

    Iterates the project's saved queries and creates shared-column drill-down
    mappings (idempotent — existing mappings are skipped, so this is safe to
    re-run). Enabling the AI scope on the Scopes page calls this so the toggle
    actually produces the mappings. Always returns the AI set (created if
    absent) even when no new mappings were found.
    """
    await _get_project(session, project_id=project_id, tenant_id=context.tenant_id)

    from app.services.auto_scope import auto_generate_project_scopes

    scope_set, _created = await auto_generate_project_scopes(
        session,
        project_id=project_id,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
    )
    await session.commit()
    await session.refresh(scope_set)
    count = await _scope_count(session, scope_set.id)
    return ScopeSetRead.model_validate(
        await _scope_set_dict(session, scope_set, count, context)
    )


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
