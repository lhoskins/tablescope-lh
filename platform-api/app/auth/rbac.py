"""Role-based access control."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from fastapi import Depends, HTTPException, status

from app.auth.context import RequestContext, get_request_context


class Role(StrEnum):
    ROOT_ADMIN = "root_admin"
    TENANT_ADMIN = "tenant_admin"
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


_ROLE_ORDER: dict[Role, int] = {
    Role.VIEWER: 0,
    Role.EDITOR: 1,
    Role.ADMIN: 2,
    Role.TENANT_ADMIN: 3,
    Role.ROOT_ADMIN: 4,
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
    """FastAPI dependency factory enforcing minimum role."""

    def _dependency(context: RequestContext = Depends(get_request_context)) -> RequestContext:
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

    def _dependency(context: RequestContext = Depends(get_request_context)) -> RequestContext:
        if context.is_service:
            return context
        if not context.has_permission(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {permission}",
            )
        return context

    return _dependency
