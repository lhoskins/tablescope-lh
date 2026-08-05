"""Shared helpers for the project routes.

Visibility subqueries, home-page project metadata and owner/sharing labels used
by ``projects_crud.py``, ``projects_aggregates.py``, ``projects_datasources.py``,
``projects_members.py``, ``projects_queries.py`` and ``projects_metadata.py``.
"""

from __future__ import annotations

import logging

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.models.project import Project, ProjectMember
from app.models.saved_query import SavedQuery
from app.models.user import User

logger = logging.getLogger(__name__)


def _derive_ai_status(
    *, doc_total: int, doc_indexing: int, doc_ready: int, has_activity: bool
) -> str:
    """Roll an AI status label up from a project's document indexing state."""
    if doc_indexing > 0:
        return "indexing"
    if doc_ready > 0:
        return "ready"
    if has_activity:
        return "active"
    return "idle"


def _visible_projects_subquery(context: RequestContext):
    """Select ids of projects the caller can see in the current tenant."""
    member_sub = select(ProjectMember.project_id).where(
        ProjectMember.user_id == context.user_id,
        ProjectMember.is_active.is_(True),
    )
    return select(Project.id, Project.name).where(
        Project.tenant_id == context.tenant_id,
        or_(
            Project.owner_id == context.user_id,
            Project.id.in_(member_sub),
        ),
    )


def _user_label(user: User) -> str:
    """A human-friendly name for a user (display name > full name > email)."""
    if user.display_name:
        return user.display_name
    full = " ".join(p for p in [user.first_name, user.last_name] if p)
    return full or user.email


class _ProjectMeta:
    __slots__ = ("is_shared", "name", "owner_id")

    def __init__(self, name: str, owner_id: int | None, is_shared: bool) -> None:
        self.name = name
        self.owner_id = owner_id
        self.is_shared = is_shared


async def _home_context(
    session: AsyncSession, context: RequestContext
) -> tuple[dict[int, _ProjectMeta], dict[int, str]]:
    """Visible-project metadata + a user-id→name map for "Shared by" labels."""
    member_sub = select(ProjectMember.project_id).where(
        ProjectMember.user_id == context.user_id,
        ProjectMember.is_active.is_(True),
    )
    rows = (
        await session.execute(
            select(
                Project.id,
                Project.name,
                Project.owner_id,
                Project.is_shared,
            ).where(
                Project.tenant_id == context.tenant_id,
                or_(
                    Project.owner_id == context.user_id,
                    Project.id.in_(member_sub),
                ),
            )
        )
    ).all()
    projects = {
        pid: _ProjectMeta(name, owner_id, is_shared)
        for pid, name, owner_id, is_shared in rows
    }
    users = list(
        await session.scalars(
            select(User).where(User.tenant_id == context.tenant_id)
        )
    )
    names = {u.id: _user_label(u) for u in users}
    return projects, names


def _shared_by(
    project: _ProjectMeta | None,
    item_owner_id: int | None,
    user_names: dict[int, str],
    *,
    item_shared: bool | None = None,
) -> str:
    """Resolve the "Shared by" label.

    - "Private" when the item (or its project) is not shared.
    - "Shared" when shared by the project owner.
    - the owner's name when shared by someone other than the project owner.
    """
    if project is None:
        return "Private"
    is_shared = project.is_shared if item_shared is None else item_shared
    if not is_shared:
        return "Private"
    if item_owner_id is None or item_owner_id == project.owner_id:
        return "Shared"
    return user_names.get(item_owner_id, "Shared")


def _owner(
    project: _ProjectMeta | None,
    item_owner_id: int | None,
    user_names: dict[int, str],
) -> tuple[int | None, str]:
    """Resolve the actual owner/creator (id, name) of an item.

    Falls back to the project owner when the item has no explicit owner.
    """
    owner_id = item_owner_id
    if owner_id is None and project is not None:
        owner_id = project.owner_id
    name = user_names.get(owner_id, "—") if owner_id is not None else "—"
    return owner_id, name


def _query_origin(query: SavedQuery) -> tuple[str, str]:
    """Normalize a saved query's origin into (key, human label)."""
    if query.ai_generated:
        return "ai_generated", "AI Generated"
    return "manual", "Manual"


async def _is_project_admin(
    session: AsyncSession, project: Project, context: RequestContext
) -> bool:
    """True if the caller is the project owner, a project-admin member, or a
    tenant admin — i.e. allowed to manage any datasource on the project."""
    if context.role == "admin":
        return True
    if project.owner_id == context.user_id:
        return True
    member = await session.get(ProjectMember, (project.id, context.user_id))
    return member is not None and member.role == "admin"
