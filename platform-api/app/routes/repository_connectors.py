"""Repository connector administration routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models import RepositoryProfile
from app.services.repository_profiler import RepositoryProfiler
from app.services.repository_scanner import (
    RepositoryScannerError,
    create_scan,
    get_scan,
    list_items,
    list_scans,
)
from app.services.repository_service import (
    RepositoryServiceError,
    create_connection,
    disable_connection,
    get_connection,
    list_connections,
    list_connector_types,
    test_connection_by_config,
    test_existing_connection,
    update_connection,
)
from app.tasks.workflows import enqueue_scan_repository_connection

router = APIRouter(prefix="/repository-connectors", tags=["Repository Connectors"])


class RepositoryConnectionCreate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=4000)
    connector_type: str = "unc"
    config: dict[str, Any] = Field(default_factory=dict)
    secret: dict[str, Any] | None = None
    project_id: int | None = None
    is_enabled: bool = True
    scan_schedule: str | None = None


class RepositoryConnectionUpdate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=4000)
    config: dict[str, Any] | None = None
    secret: dict[str, Any] | None = None
    project_id: int | None = None
    is_enabled: bool | None = None
    scan_schedule: str | None = None
    expected_version: int


class RepositoryConnectionTestRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    connector_type: str = "unc"
    config: dict[str, Any] = Field(default_factory=dict)
    secret: dict[str, Any] = Field(default_factory=dict)


class RepositoryItemQueryParams:
    def __init__(
        self,
        item_type: str | None = Query(None, description="file, directory, symlink or other"),
        include_deleted: bool = Query(False),
        extraction_status: str | None = Query(None),
        search: str | None = Query(None, max_length=255),
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ) -> None:
        self.item_type = item_type
        self.is_deleted = None if include_deleted else False
        self.extraction_status = extraction_status
        self.search = search
        self.limit = limit
        self.offset = offset


def _ok_or_400(result: dict[str, Any]) -> dict[str, Any]:
    if not result.get("success"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result)
    return result


@router.get("/types", response_model=list[dict[str, Any]])
async def get_repository_connector_types(
    context: RequestContext = Depends(require_role(Role.TENANT_ADMIN)),
) -> list[dict[str, Any]]:
    """List registered repository connector types."""
    return await list_connector_types()


@router.get("/", response_model=list[dict[str, Any]])
async def get_repository_connections(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.TENANT_ADMIN)),
) -> list[dict[str, Any]]:
    """List repository connections for the current tenant."""
    return await list_connections(session, context.tenant_id)


@router.post("/", response_model=dict[str, Any], status_code=status.HTTP_201_CREATED)
async def post_repository_connection(
    body: RepositoryConnectionCreate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.TENANT_ADMIN)),
) -> dict[str, Any]:
    """Create a new repository connection."""
    try:
        return await create_connection(
            session,
            context.tenant_id,
            context.user_id,
            body.model_dump(exclude_unset=True),
        )
    except RepositoryServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{connection_id}", response_model=dict[str, Any])
async def get_repository_connection(
    connection_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.TENANT_ADMIN)),
) -> dict[str, Any]:
    """Return a single repository connection (secret is never included)."""
    try:
        return await get_connection(session, context.tenant_id, connection_id)
    except RepositoryServiceError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/{connection_id}", response_model=dict[str, Any])
async def patch_repository_connection(
    connection_id: int,
    body: RepositoryConnectionUpdate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.TENANT_ADMIN)),
) -> dict[str, Any]:
    """Update a repository connection with optimistic versioning."""
    try:
        return await update_connection(
            session,
            context.tenant_id,
            context.user_id,
            connection_id,
            body.model_dump(exclude_unset=True, exclude={"expected_version"}),
            body.expected_version,
        )
    except RepositoryServiceError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete("/{connection_id}", response_model=dict[str, Any])
async def delete_repository_connection(
    connection_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.TENANT_ADMIN)),
) -> dict[str, Any]:
    """Disable a repository connection without removing scan history."""
    try:
        return await disable_connection(session, context.tenant_id, connection_id, context.user_id)
    except RepositoryServiceError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/test", response_model=dict[str, Any])
async def test_repository_connector_config(
    body: RepositoryConnectionTestRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.TENANT_ADMIN)),
) -> dict[str, Any]:
    """Test a connector configuration without saving it."""
    try:
        result = await test_connection_by_config(
            session,
            context.tenant_id,
            body.model_dump(),
        )
    except RepositoryServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _ok_or_400(result)


@router.post("/{connection_id}/test", response_model=dict[str, Any])
async def test_existing_repository_connector(
    connection_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.TENANT_ADMIN)),
) -> dict[str, Any]:
    """Test an existing stored repository connection."""
    try:
        result = await test_existing_connection(session, context.tenant_id, connection_id)
    except RepositoryServiceError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _ok_or_400(result)


@router.post("/{connection_id}/scans", response_model=dict[str, Any], status_code=status.HTTP_202_ACCEPTED)
async def start_repository_scan(
    connection_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.TENANT_ADMIN)),
) -> dict[str, Any]:
    """Create a scan record and enqueue the background scanner."""
    try:
        scan = await create_scan(session, context.tenant_id, connection_id, trigger_type="manual")
        job_id = await enqueue_scan_repository_connection(
            tenant_id=context.tenant_id,
            connection_id=connection_id,
            scan_id=scan.id,
        )
        return {
            **scan.to_summary_dict(),
            "job_id": job_id,
        }
    except RepositoryServiceError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RepositoryScannerError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{connection_id}/scans", response_model=list[dict[str, Any]])
async def get_repository_scans(
    connection_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.TENANT_ADMIN)),
) -> list[dict[str, Any]]:
    """List scan history for a repository connection."""
    try:
        return await list_scans(session, context.tenant_id, connection_id)
    except RepositoryScannerError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{connection_id}/scans/{scan_id}", response_model=dict[str, Any])
async def get_repository_scan(
    connection_id: int,
    scan_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.TENANT_ADMIN)),
) -> dict[str, Any]:
    """Return a single scan record."""
    try:
        return await get_scan(session, context.tenant_id, connection_id, scan_id)
    except RepositoryScannerError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{connection_id}/profile", response_model=dict[str, Any])
async def get_repository_profile(
    connection_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.TENANT_ADMIN)),
) -> dict[str, Any]:
    """Return the latest profile for a repository connection, or build one if missing."""
    result = await session.execute(
        select(RepositoryProfile)
        .where(
            RepositoryProfile.connection_id == connection_id,
            RepositoryProfile.tenant_id == context.tenant_id,
            RepositoryProfile.is_current.is_(True),
        )
        .order_by(RepositoryProfile.created_at.desc())
    )
    profile = result.scalars().first()
    if profile:
        return profile.to_dict()

    # No profile yet — build from existing items on demand.
    profile_data = await RepositoryProfiler.build_profile(
        session, connection_id, scan_id=None, tenant_id=context.tenant_id
    )
    return profile_data


@router.get("/{connection_id}/items", response_model=dict[str, Any])
async def get_repository_items(
    connection_id: int,
    params: RepositoryItemQueryParams = Depends(),
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.TENANT_ADMIN)),
) -> dict[str, Any]:
    """List repository items for a connection."""
    try:
        items, total = await list_items(
            session,
            context.tenant_id,
            connection_id,
            item_type=params.item_type,
            is_deleted=params.is_deleted,
            extraction_status=params.extraction_status,
            search=params.search,
            limit=params.limit,
            offset=params.offset,
        )
    except RepositoryScannerError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {
        "items": items,
        "total": total,
        "limit": params.limit,
        "offset": params.offset,
    }
