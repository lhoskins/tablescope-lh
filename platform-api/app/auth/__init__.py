"""Authentication, authorization, and tenant resolution."""

from app.auth.context import RequestContext, get_request_context
from app.auth.jwt import (
    AuthError,
    TokenClaims,
    create_access_token,
    decode_access_token,
)
from app.auth.rbac import Role, require_role

__all__ = [
    "AuthError",
    "RequestContext",
    "Role",
    "TokenClaims",
    "create_access_token",
    "decode_access_token",
    "get_request_context",
    "require_role",
]
