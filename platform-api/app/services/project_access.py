"""The single project-access policy (TS-ISO-003).

The tenant/project isolation security assessment found at least 6 divergent,
independently-hand-rolled project ownership/membership checks scattered
across route modules -- most agreeing with each other, but not all: several
granted a shared project to *any* same-tenant user without checking active
membership at all (see `docs/devin-*-ts-iso-003-*.md` for the concrete
instances found and fixed), which is a real gap against the stated policy
below. This module is the one place that rule should live; new route
modules should call `authorize_project_access` rather than writing another
ad hoc version of it.

Policy: a project is accessible to a user if and only if
  - the user owns it, or
  - the user has an ACTIVE `ProjectMember` row for it.
`Project.is_shared` controls whether the project is discoverable/joinable by
other tenant members -- it is not itself a grant of access. Same-tenant
alone is never sufficient; cross-tenant is never sufficient.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project, ProjectMember


async def authorize_project_access(
    session: AsyncSession,
    *,
    tenant_id: int,
    user_id: int,
    project_id: int,
) -> Project:
    """Verify ``user_id`` has access to ``project_id`` within ``tenant_id``.

    Raises 404 if the project doesn't exist in the caller's tenant (so a
    cross-tenant id never distinguishes "not found" from "not authorized"),
    403 if it exists but the caller is neither owner nor an active member.
    """
    stmt = select(Project).where(
        Project.id == project_id,
        Project.tenant_id == tenant_id,
    )
    result = await session.execute(stmt)
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found in your tenant",
        )

    if project.owner_id == user_id:
        return project

    member_stmt = select(ProjectMember).where(
        ProjectMember.project_id == project_id,
        ProjectMember.user_id == user_id,
        ProjectMember.is_active.is_(True),
    )
    member_result = await session.execute(member_stmt)
    if member_result.scalar_one_or_none():
        return project

    if project.is_shared:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this project",
        )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="This is a private project and you are not the owner",
    )
