"""Role-based access control."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext, get_request_context
from app.auth.membership import require_membership
from app.database import get_db
from app.models.user import User


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


def require_role(
    required: Role,
) -> Callable[[RequestContext], Awaitable[RequestContext]]:
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


def require_permission(
    permission: str,
) -> Callable[[RequestContext], Awaitable[RequestContext]]:
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


async def require_platform_admin(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
) -> RequestContext:
    """Platform-scoped administrator guard.

    Authorises super-admins, the global ``root_admin`` role, and service
    identities. Unlike :func:`require_role`, this does *not* require an active
    tenant membership, because platform infrastructure (LLM runtimes, model
    deployments) is not tenant-scoped.

    Service callers are allowed because this guard is intended for read and
    worker-driven paths. Mutating governance actions such as approval,
    activation, rollback, and deletion require :func:`require_human_platform_admin`.
    """
    if context.is_service:
        return context
    user = await session.get(User, context.user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authentication required",
        )
    if user.is_super_admin or user.role == Role.ROOT_ADMIN:
        return context
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Requires platform administrator",
    )


async def require_human_platform_admin(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
) -> RequestContext:
    """Platform-scoped administrator guard that rejects service identities.

    Use this for governance mutations (approve, activate, rollback, delete,
    quarantine-release) where the service identity must not be able to unilaterally
    change platform infrastructure. A service key must never approve its own
    production replacement.
    """
    if context.is_service:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Service identities cannot perform this action",
        )
    return await require_platform_admin(session=session, context=context)
