"""Transaction-scoped PostgreSQL row-level-security context.

The application never authorizes a request from these values alone.  They are
the database-side copy of an already authenticated/authorized principal and
exist so PostgreSQL can independently reject a missing tenant predicate.

Context is held in :mod:`contextvars`, which keeps concurrent ASGI requests and
worker tasks isolated.  The SQLAlchemy ``after_begin`` hook writes the values
with ``set_config(..., true)`` (the equivalent of ``SET LOCAL``), so pooled
connections cannot retain a principal after the transaction ends.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session as SyncSession

from app.config import get_settings


@dataclass(frozen=True, slots=True)
class RlsPrincipal:
    tenant_id: int
    user_id: int
    project_id: int | None = None
    source: str = "request"


_principal: ContextVar[RlsPrincipal | None] = ContextVar(
    "tablescope_rls_principal", default=None
)


def current_rls_principal() -> RlsPrincipal | None:
    """Return the principal bound to the current async execution context."""

    return _principal.get()


def _validate_identifier(value: int | None, *, name: str, allow_zero: bool) -> None:
    if value is None:
        return
    minimum = 0 if allow_zero else 1
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        comparator = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{name} must be a {comparator} integer")


@contextmanager
def rls_scope(
    *,
    tenant_id: int,
    user_id: int,
    project_id: int | None = None,
    source: str = "request",
) -> Iterator[RlsPrincipal]:
    """Bind a principal until the surrounding request/task completes.

    ``user_id=0`` is reserved for the pre-authentication bootstrap after a
    tenant slug has been resolved.  ``tenant_id=0`` is intentionally not
    accepted: service callers must bind the concrete tenant they are acting
    for instead of receiving a global RLS bypass.
    """

    _validate_identifier(tenant_id, name="tenant_id", allow_zero=False)
    _validate_identifier(user_id, name="user_id", allow_zero=True)
    _validate_identifier(project_id, name="project_id", allow_zero=False)
    if not source.strip():
        raise ValueError("source must not be empty")

    principal = RlsPrincipal(
        tenant_id=tenant_id,
        user_id=user_id,
        project_id=project_id,
        source=source.strip(),
    )
    token: Token[RlsPrincipal | None] = _principal.set(principal)
    try:
        yield principal
    finally:
        _principal.reset(token)


def _context_parameters(principal: RlsPrincipal | None) -> dict[str, str]:
    """Render only validated integers into transaction-local GUC values."""

    if principal is None:
        return {"tenant_id": "", "user_id": "", "project_id": ""}
    return {
        "tenant_id": str(principal.tenant_id),
        "user_id": str(principal.user_id),
        "project_id": "" if principal.project_id is None else str(principal.project_id),
    }


_SET_CONTEXT_SQL = text(
    """
    SELECT
      set_config('tablescope.tenant_id', :tenant_id, true),
      set_config('tablescope.user_id', :user_id, true),
      set_config('tablescope.project_id', :project_id, true)
    """
)


def _is_postgres(connection: Connection) -> bool:
    return connection.dialect.name == "postgresql"


@event.listens_for(SyncSession, "after_begin")
def _inject_rls_context(
    session: SyncSession, transaction: object, connection: Connection
) -> None:
    """Install the current principal at the beginning of every transaction."""

    del session, transaction
    settings = get_settings()
    if not settings.postgres_rls_context_enabled or not _is_postgres(connection):
        return

    principal = current_rls_principal()
    # Empty values are deliberate.  The database helper converts them to NULL,
    # so a missing context returns no tenant rows instead of inheriting state
    # from a pooled connection or accidentally becoming tenant zero.
    connection.execute(_SET_CONTEXT_SQL, _context_parameters(principal))


async def set_rls_session_context(
    session: AsyncSession,
    *,
    tenant_id: int,
    user_id: int = 0,
    project_id: int | None = None,
) -> None:
    """Set context after an anonymous auth flow resolves a tenant slug.

    Normal authenticated requests and correctly wrapped workers use
    :func:`rls_scope` and receive automatic transaction setup.  This explicit
    helper is only for login/SSO bootstrap, where the tenant is not known until
    the global ``tenants`` table has been queried.
    """

    _validate_identifier(tenant_id, name="tenant_id", allow_zero=False)
    _validate_identifier(user_id, name="user_id", allow_zero=True)
    _validate_identifier(project_id, name="project_id", allow_zero=False)
    if not get_settings().postgres_rls_context_enabled:
        return
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return
    await session.execute(
        _SET_CONTEXT_SQL,
        _context_parameters(
            RlsPrincipal(
                tenant_id=tenant_id,
                user_id=user_id,
                project_id=project_id,
                source="auth-bootstrap",
            )
        ),
    )

