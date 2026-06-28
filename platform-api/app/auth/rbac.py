"""Role-based access control."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from fastapi import Depends, HTTPException, status

from app.auth.context import RequestContext
from app.auth.membership import require_membership


class Role(StrEnum):
    ROOT_ADMIN = "root_admin"
    TENANT_ADMIN = "tenant_admin"
    ADMIN = "admin"
    DB_ADMIN = "db_admin"
    EDITOR = "editor"
    MEMBER = "member"
    VIEWER = "viewer"


_ROLE_ORDER: dict[Role, int] = {
    Role.VIEWER: 0,
    Role.MEMBER: 1,
    Role.EDITOR: 1,
    Role.DB_ADMIN: 2,
    Role.ADMIN: 3,
    Role.TENANT_ADMIN: 4,
    Role.ROOT_ADMIN: 5,
}


def _at_least(actual: str, required: Role) -> bool:
    try:
        actual_role = Role(actual)
    except ValueError:
        return False
    return _ROLE_ORDER[actual_role] >= _ROLE_ORDER[required]


def has_role(actual: str, required: Role) -> bool:
    """Public predicate: does ``actual`` meet or exceed ``required``?

    Use this for imperative permission checks inside service/route code (the
    FastAPI dependency :func:`require_role` is for declarative route gating).
    """
    return _at_least(actual, required)


def require_role(required: Role) -> Callable[[RequestContext], RequestContext]:
    """FastAPI dependency factory enforcing minimum role.

    Membership (active, tenant-scoped) is verified first via
    :func:`require_membership`, which also pins the effective role from the DB.
    """

    async def _dependency(
        context: RequestContext = Depends(require_membership),
    ) -> RequestContext:
        if context.is_service:
            return context
        if not _at_least(context.role, required):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role: {required.value}",
            )
        return context

    return _dependency


def require_permission(permission: str) -> Callable[[RequestContext], RequestContext]:
    """FastAPI dependency factory enforcing a specific permission."""

    async def _dependency(
        context: RequestContext = Depends(require_membership),
    ) -> RequestContext:
        if context.is_service:
            return context
        if not context.has_permission(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {permission}",
            )
        return context

    return _dependency
