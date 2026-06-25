"""DB Admin data source assignment routes (issue 5).

Lets an Admin or DB Admin assign already-configured database datasources to
users.  Assigned sources appear in the user's Data Source Builder under
"Connected Databases" without ever exposing the underlying credentials.

All endpoints require at least the DB Admin role; Members cannot assign.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.database_data_source import DatabaseDataSource
from app.models.database_data_source_assignment import (
    DatabaseDataSourceAssignment,
)
from app.models.user import User
from app.schemas.data_source_assignment import (
    AssignableSource,
    AssignableUser,
    AssignmentCreate,
    AssignmentRead,
    AssignmentUpdate,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["data-source-assignments"])


def _user_name(user: User | None) -> str | None:
    if user is None:
        return None
    if user.display_name:
        return user.display_name
    first = (user.first_name or "").strip()
    last = (user.last_name or "").strip()
    full = f"{first} {last}".strip()
    return full or user.email


async def _serialize(
    session: AsyncSession, assignment: DatabaseDataSourceAssignment
) -> AssignmentRead:
    assigned_user = await session.get(User, assignment.assigned_user_id)
    assigner = (
        await session.get(User, assignment.assigned_by)
        if assignment.assigned_by
        else None
    )
    source = await session.get(
        DatabaseDataSource, assignment.database_data_source_id
    )
    return AssignmentRead(
        id=assignment.id,
        database_data_source_id=assignment.database_data_source_id,
        database_connection_id=assignment.database_connection_id,
        assigned_user_id=assignment.assigned_user_id,
        assigned_user_email=assigned_user.email if assigned_user else None,
        assigned_user_name=_user_name(assigned_user),
        friendly_name=assignment.friendly_name,
        read_only=assignment.read_only,
        is_active=assignment.is_active,
        assigned_by=assignment.assigned_by,
        assigned_by_name=_user_name(assigner),
        datasource_name=source.display_name if source else None,
        db_type=source.db_type if source else None,
        created_at=assignment.created_at.isoformat()
        if assignment.created_at
        else None,
    )


@router.get("/assignable-db-sources", response_model=list[AssignableSource])
async def list_assignable_db_sources(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.DB_ADMIN)),
) -> list[AssignableSource]:
    """Configured (non-archived) database datasources in the tenant."""
    rows = (
        await session.scalars(
            select(DatabaseDataSource).where(
                DatabaseDataSource.tenant_id == context.tenant_id,
                DatabaseDataSource.archived.is_(False),
            )
        )
    ).all()
    return [
        AssignableSource(
            database_data_source_id=r.id,
            database_connection_id=None,
            display_name=r.display_name,
            db_type=r.db_type,
            host=r.host,
            database_name=r.database_name,
            table_name=r.table_name,
        )
        for r in rows
    ]


@router.get("/assignable-users", response_model=list[AssignableUser])
async def list_assignable_users(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.DB_ADMIN)),
) -> list[AssignableUser]:
    rows = (
        await session.scalars(
            select(User).where(
                User.tenant_id == context.tenant_id,
                User.is_active.is_(True),
            )
        )
    ).all()
    return [
        AssignableUser(
            id=u.id,
            email=u.email,
            display_name=_user_name(u),
            role=u.role,
        )
        for u in rows
    ]


@router.get("/data-source-assignments", response_model=list[AssignmentRead])
async def list_assignments(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.DB_ADMIN)),
) -> list[AssignmentRead]:
    rows = (
        await session.scalars(
            select(DatabaseDataSourceAssignment)
            .where(DatabaseDataSourceAssignment.tenant_id == context.tenant_id)
            .order_by(DatabaseDataSourceAssignment.id.desc())
        )
    ).all()
    return [await _serialize(session, r) for r in rows]


@router.post("/data-source-assignments", response_model=list[AssignmentRead])
async def create_assignments(
    body: AssignmentCreate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.DB_ADMIN)),
) -> list[AssignmentRead]:
    source = await session.get(
        DatabaseDataSource, body.database_data_source_id
    )
    if source is None or source.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Datasource not found")

    created: list[DatabaseDataSourceAssignment] = []
    for user_id in dict.fromkeys(body.assigned_user_ids):
        user = await session.get(User, user_id)
        if user is None or user.tenant_id != context.tenant_id:
            raise HTTPException(
                status_code=404, detail=f"User {user_id} not found in tenant"
            )
        existing = await session.scalar(
            select(DatabaseDataSourceAssignment).where(
                DatabaseDataSourceAssignment.tenant_id == context.tenant_id,
                DatabaseDataSourceAssignment.database_data_source_id
                == body.database_data_source_id,
                DatabaseDataSourceAssignment.assigned_user_id == user_id,
            )
        )
        if existing is not None:
            # Re-assigning an existing (possibly removed) pairing: refresh it
            # rather than violating the unique constraint.
            existing.friendly_name = body.friendly_name
            existing.read_only = body.read_only
            existing.is_active = True
            existing.assigned_by = context.user_id
            created.append(existing)
        else:
            assignment = DatabaseDataSourceAssignment(
                tenant_id=context.tenant_id,
                database_data_source_id=body.database_data_source_id,
                database_connection_id=None,
                assigned_user_id=user_id,
                friendly_name=body.friendly_name,
                read_only=body.read_only,
                is_active=True,
                assigned_by=context.user_id,
            )
            session.add(assignment)
            created.append(assignment)
    await session.commit()
    for a in created:
        await session.refresh(a)
    return [await _serialize(session, a) for a in created]


@router.put(
    "/data-source-assignments/{assignment_id}",
    response_model=AssignmentRead,
)
async def update_assignment(
    assignment_id: int,
    body: AssignmentUpdate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.DB_ADMIN)),
) -> AssignmentRead:
    assignment = await session.get(
        DatabaseDataSourceAssignment, assignment_id
    )
    if assignment is None or assignment.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Assignment not found")
    if body.friendly_name is not None:
        assignment.friendly_name = body.friendly_name
    if body.read_only is not None:
        assignment.read_only = body.read_only
    if body.is_active is not None:
        assignment.is_active = body.is_active
    await session.commit()
    await session.refresh(assignment)
    return await _serialize(session, assignment)


@router.delete("/data-source-assignments/{assignment_id}")
async def delete_assignment(
    assignment_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.DB_ADMIN)),
) -> dict:
    assignment = await session.get(
        DatabaseDataSourceAssignment, assignment_id
    )
    if assignment is None or assignment.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Assignment not found")
    await session.delete(assignment)
    await session.commit()
    return {"status": "deleted", "id": assignment_id}
