"""Tenant lifecycle guard middleware.

Re-validates the tenant lifecycle status on every authenticated request so an
existing JWT cannot continue operating after a decommission begins. Returns a
``423 Locked`` response for any tenant-scoped request when the tenant is
``decommissioning`` or ``decommissioned``.

Decommission status/export endpoints and anonymous/public paths are exempt.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware

from app.auth.context import RequestContext
from app.database import SessionLocal
from app.models.tenant import Tenant

logger = logging.getLogger(__name__)

# Paths that are allowed while a tenant is decommissioning. Decommission status,
# audit export, and public health/auth callbacks must remain reachable.
_LIFECYCLE_EXEMPT_PATH_RE = re.compile(
    r"^/(health|metrics|openapi\.json|docs|redoc|api/auth|api/mfa|api/billing/stripe/webhook|api/admin/tenant-decommission|api/admin/tenants/[^/]+/decommission)"
)


async def _is_active_tenant(session: AsyncSession, tenant_id: int) -> bool | None:
    """Return True/False for known tenants, None for missing tenant_id."""
    if tenant_id is None or tenant_id <= 0:
        return True
    tenant = await session.scalar(select(Tenant.id).where(Tenant.id == tenant_id))
    if tenant is None:
        # Tenant does not exist; let downstream route handlers return 404 so the
        # lifecycle middleware does not leak tenant existence.
        return True
    row = await session.scalar(
        select(Tenant.lifecycle_status).where(Tenant.id == tenant_id)
    )
    return row == "active"


class TenantLifecycleMiddleware(BaseHTTPMiddleware):
    """Block tenant activity when the tenant is decommissioning/decommissioned."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path
        if _LIFECYCLE_EXEMPT_PATH_RE.match(path):
            return await call_next(request)

        context: RequestContext | None = getattr(request.state, "context", None)
        if context is None or context.is_service or context.tenant_id is None:
            # Anonymous or service/platform-scoped requests are not blocked here.
            return await call_next(request)

        async with SessionLocal() as session:
            try:
                active = await _is_active_tenant(session, context.tenant_id)
            except Exception:
                logger.exception(
                    "Tenant lifecycle check failed for tenant %s", context.tenant_id
                )
                # Fail-closed only when we are certain; a DB hiccup should not
                # lock every tenant out.
                return await call_next(request)

        if active is False:
            logger.warning(
                "Blocked request to %s for decommissioning tenant %s",
                path,
                context.tenant_id,
            )
            return JSONResponse(
                status_code=423,
                content={
                    "detail": "Tenant is decommissioning and cannot be modified.",
                    "code": "TENANT_DECOMMISSIONING",
                },
            )

        return await call_next(request)
