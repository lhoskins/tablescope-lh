"""Scope management routes.

CRUD over drill-down scopes. Tenant isolation is enforced in the service
layer; routes simply pass `context.tenant_id` through.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.auth.context import RequestContext
from app.auth.membership import require_membership
from app.auth.rbac import Role, require_role
from app.schemas.scope import ScopeCreate, ScopeRead, ScopeUpdate
from app.services.scope_proxy import ScopeError, ScopeNotFoundError, ScopeProxyService

router = APIRouter(prefix="/scopes", tags=["scopes"])


def get_scope_service() -> ScopeProxyService:
    return ScopeProxyService()


@router.get("", response_model=list[ScopeRead])
async def list_scopes(
    context: RequestContext = Depends(require_membership),
    service: ScopeProxyService = Depends(get_scope_service),
) -> list[ScopeRead]:
    scopes = await service.list_scopes(tenant_id=context.tenant_id)
    return [ScopeRead.model_validate(s.to_dict()) for s in scopes]


@router.post("", response_model=ScopeRead, status_code=status.HTTP_201_CREATED)
async def create_scope(
    payload: ScopeCreate,
    context: RequestContext = Depends(require_role(Role.EDITOR)),
    service: ScopeProxyService = Depends(get_scope_service),
) -> ScopeRead:
    try:
        scope = await service.create_scope(
            tenant_id=context.tenant_id,
            source_table=payload.sourceTable,
            source_column=payload.sourceColumn,
            target_table=payload.targetTable,
            target_column=payload.targetColumn,
        )
    except ScopeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ScopeRead.model_validate(scope.to_dict())


@router.get("/{source_table}/{source_column}", response_model=ScopeRead)
async def get_scope(
    source_table: str,
    source_column: str,
    context: RequestContext = Depends(require_membership),
    service: ScopeProxyService = Depends(get_scope_service),
) -> ScopeRead:
    try:
        scope = await service.get_scope(
            tenant_id=context.tenant_id,
            source_table=source_table,
            source_column=source_column,
        )
    except ScopeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ScopeRead.model_validate(scope.to_dict())


@router.put("/{source_table}/{source_column}", response_model=ScopeRead)
async def update_scope(
    source_table: str,
    source_column: str,
    payload: ScopeUpdate,
    context: RequestContext = Depends(require_role(Role.EDITOR)),
    service: ScopeProxyService = Depends(get_scope_service),
) -> ScopeRead:
    try:
        scope = await service.update_scope(
            tenant_id=context.tenant_id,
            source_table=source_table,
            source_column=source_column,
            target_table=payload.targetTable,
            target_column=payload.targetColumn,
        )
    except ScopeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ScopeRead.model_validate(scope.to_dict())


@router.delete(
    "/{source_table}/{source_column}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_scope(
    source_table: str,
    source_column: str,
    context: RequestContext = Depends(require_role(Role.EDITOR)),
    service: ScopeProxyService = Depends(get_scope_service),
) -> Response:
    try:
        await service.delete_scope(
            tenant_id=context.tenant_id,
            source_table=source_table,
            source_column=source_column,
        )
    except ScopeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
