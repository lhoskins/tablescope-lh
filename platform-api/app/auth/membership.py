"""DB-backed tenant-membership enforcement.

The JWT carries ``tenant_id``/``user_id``/``role`` claims, but a token stays
valid until it expires — so a user who was deactivated, removed from the tenant,
or had their role changed would keep their old access for the life of the token.

:func:`require_membership` re-validates the caller against the database on every
request: the user must still exist as a member of the *current* tenant, the
membership must be active, and the effective role is resolved from the
membership row (not the possibly-stale token claim). This is the single
chokepoint enforcing tenant isolation for authenticated routes.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext, get_request_context
from app.database import get_db
from app.models.user import User


async def require_membership(
    context: RequestContext = Depends(get_request_context),
    session: AsyncSession = Depends(get_db),
) -> RequestContext:
    """Verify the caller is an active member of the request's tenant.

    Service callers (trusted machine-to-machine) bypass this check. For user
    tokens we confirm the membership row exists in the current tenant and is
    active, then pin the context role to the membership's role.
    """
    if context.is_service:
        return context

    user = await session.get(User, context.user_id)
    # No membership row, or the token's tenant doesn't match the user's tenant
    # membership → the caller is not a member of this tenant.
    if user is None or user.tenant_id != context.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this tenant",
        )
    if not user.is_active or (user.status or "active") != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your access to this tenant is inactive",
        )

    # Resolve the effective role from the membership, so role changes take
    # effect immediately rather than waiting for the token to expire.
    if user.role and context.claims.role != user.role:
        context.claims.role = user.role
    return context
