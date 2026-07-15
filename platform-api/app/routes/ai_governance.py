"""AI governance administration routes.

Tenant administrators can view and update the analytical methods their
organization permits, and auditors can inspect the immutable governance log.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.services.ai_governance import (
    AIGovernanceService,
    PolicyVersionConflict,
    list_method_definitions,
)

router = APIRouter(prefix="/ai-governance", tags=["AI Governance"])


def _service() -> AIGovernanceService:
    from app.services.ai_governance import ai_governance_service

    return ai_governance_service


class MethodPolicyItem(BaseModel):
    method_key: str
    enabled: bool
    reason: str | None = None


class BulkPolicyRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    methods: list[MethodPolicyItem] = Field(..., min_length=1)
    expected_version: int


class SinglePolicyRequest(BaseModel):
    enabled: bool
    reason: str | None = None
    expected_version: int


class PolicyResponse(BaseModel):
    tenant_id: int
    version: int
    is_default: bool
    methods: dict[str, Any]


@router.get("/policy", response_model=PolicyResponse)
async def get_policy(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.TENANT_ADMIN)),
) -> dict[str, Any]:
    """Return the effective analytical-method policy for the current tenant."""
    policy = await _service().get_effective_policy(session, context.tenant_id)
    return {
        "tenant_id": policy["tenantId"],
        "version": policy["version"],
        "is_default": policy["isDefault"],
        "methods": policy["methods"],
    }


@router.get("/capabilities", response_model=dict[str, Any])
async def get_capabilities(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    """Return only the methods currently enabled for this tenant.

    This is a public-facing subset suitable for UI filtering and suggested
    questions; no administrative metadata is exposed.
    """
    policy = await _service().get_effective_policy(session, context.tenant_id)
    return {
        "version": policy["version"],
        "methods": {
            k: v
            for k, v in policy["methods"].items()
            if v.get("enabled")
        },
    }


@router.patch("/methods/{method_key}", response_model=PolicyResponse)
async def update_method_policy(
    method_key: str,
    req: SinglePolicyRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.TENANT_ADMIN)),
) -> dict[str, Any]:
    """Enable or disable one analytical method for the current tenant."""
    try:
        policy = await _service().update_method_policy(
            session,
            context.tenant_id,
            context.user_id,
            method_key,
            req.enabled,
            req.reason,
            req.expected_version,
        )
    except PolicyVersionConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "policy_version_conflict", "current_version": exc.current_version},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {
        "tenant_id": policy["tenantId"],
        "version": policy["version"],
        "is_default": policy["isDefault"],
        "methods": policy["methods"],
    }


@router.put("/policy", response_model=PolicyResponse)
async def bulk_update_policy(
    req: BulkPolicyRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.TENANT_ADMIN)),
) -> dict[str, Any]:
    """Update many method policies in one transaction."""
    try:
        policy = await _service().bulk_update_method_policy(
            session,
            context.tenant_id,
            context.user_id,
            [item.model_dump() for item in req.methods],
            req.expected_version,
        )
    except PolicyVersionConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "policy_version_conflict", "current_version": exc.current_version},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {
        "tenant_id": policy["tenantId"],
        "version": policy["version"],
        "is_default": policy["isDefault"],
        "methods": policy["methods"],
    }


class AuditQueryParams(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    event_type: str | None = None
    method_key: str | None = None
    decision: str | None = None
    actor_user_id: int | None = None
    start: str | None = None
    end: str | None = None
    limit: int = 50
    offset: int = 0


@router.get("/audit")
async def list_audit(
    params: AuditQueryParams = Depends(),
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.TENANT_ADMIN)),
) -> dict[str, Any]:
    """List append-only AI governance audit events for the current tenant."""
    return await _service().list_audit_events(
        session,
        context.tenant_id,
        event_type=params.event_type,
        method_key=params.method_key,
        decision=params.decision,
        actor_user_id=params.actor_user_id,
        start=params.start,
        end=params.end,
        limit=params.limit,
        offset=params.offset,
    )


@router.get("/method-catalog")
async def get_method_catalog(
    context: RequestContext = Depends(require_role(Role.TENANT_ADMIN)),
) -> dict[str, Any]:
    """Return the system method registry (metadata only, no tenant overrides)."""
    return {
        "methods": [
            {
                "key": m.key,
                "displayName": m.display_name,
                "description": m.description,
                "category": m.category,
                "riskLevel": m.risk_level,
                "requiresSql": m.requires_sql,
                "experimental": m.experimental,
                "defaultEnabled": m.default_enabled,
                "supportsFallback": m.supports_fallback,
                "fallbackMethodKeys": list(m.fallback_method_keys),
            }
            for m in list_method_definitions()
        ]
    }
