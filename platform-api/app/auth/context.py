"""Per-request authentication context (extracted by middleware).

`RequestContext` is attached to `request.state.context` by `AuthMiddleware`
and exposed via the `get_request_context` FastAPI dependency.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status

from app.auth.jwt import TokenClaims


@dataclass(slots=True)
class RequestContext:
    """Authenticated request context, including tenant + user info."""

    claims: TokenClaims
    is_service: bool = False

    @property
    def tenant_id(self) -> int:
        return self.claims.tenant_id

    @property
    def user_id(self) -> int:
        return self.claims.user_id

    @property
    def role(self) -> str:
        return self.claims.role

    @property
    def permissions(self) -> list[str]:
        return self.claims.permissions

    @property
    def aal(self) -> str | None:
        """Supabase assurance level carried through the first-party token."""
        return self.claims.aal

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions


def get_request_context(request: Request) -> RequestContext:
    """FastAPI dependency that returns the request context.

    Raises 401 if there is no authenticated context (i.e. the endpoint was
    reached without going through `AuthMiddleware`).
    """
    context: RequestContext | None = getattr(request.state, "context", None)
    if context is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return context


RequestContextDep = Depends(get_request_context)
