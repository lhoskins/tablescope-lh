"""Admin API for the governed Analytical Method Reference Catalog.

Read-only browsing of the seeded method catalog — overview counts, a
filterable/paginated method list, and per-method detail — powering the admin
"Analytical Methods" page. Selection/execution stay in the engine; this surface
only exposes what the catalog contains and which methods are live.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.services.analytical_method_engine.catalog_browser import (
    get_catalog_overview,
    get_method_detail,
    list_methods,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai/methods", tags=["analytical-methods"])


@router.get("/catalog")
async def method_catalog_overview(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    overview = await get_catalog_overview(session)
    if overview is None:
        raise HTTPException(status_code=404, detail="Analytical method catalog not seeded")
    return overview


@router.get("")
async def list_analytical_methods(
    tier: int | None = Query(None, ge=1, le=4),
    status: str | None = Query(None),
    category: str | None = Query(None),
    q: str | None = Query(None, min_length=1),
    executable: bool | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    return await list_methods(
        session,
        tier=tier,
        status=status,
        category=category,
        query=q,
        executable=executable,
        limit=limit,
        offset=offset,
    )


@router.get("/{method_id}")
async def analytical_method_detail(
    method_id: str,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    detail = await get_method_detail(session, method_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Method not found")
    return detail
