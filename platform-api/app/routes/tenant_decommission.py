"""Admin endpoints for orchestrated tenant decommission."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import require_human_platform_admin
from app.database import get_db
from app.models.tenant_decommission import TenantDecommissionEvent, TenantDecommissionJob
from app.schemas.tenant_decommission import (
    DecommissionApproveRequest,
    DecommissionEventRead,
    DecommissionJobDetail,
    DecommissionPreviewRequest,
    DecommissionPreviewResponse,
    DecommissionRequest,
    DecommissionRetryResponse,
    DecommissionRunnerCallback,
)
from app.services.tenant_decommission_service import (
    DecommissionError,
    TenantDecommissionService,
)

router = APIRouter()


async def _service(session: AsyncSession) -> TenantDecommissionService:
    return TenantDecommissionService(session)


def _sha() -> tuple[str, str]:
    # Placeholder: in CI/deployment these are stamped from the git SHAs.
    return ("unknown", "unknown")


def _to_summary(job: TenantDecommissionJob) -> dict:
    return {
        "id": job.id,
        "tenant_pk": job.tenant_pk,
        "tenant_slug": job.tenant_slug,
        "data_plane_tenant_id": job.data_plane_tenant_id,
        "status": job.status,
        "current_step": job.current_step,
        "requested_by": job.requested_by,
        "approved_by": job.approved_by,
        "reason": job.reason,
        "attempt": job.attempt,
        "error_code": job.error_code,
        "error_message_safe": job.error_message_safe,
        "requested_at": job.requested_at.isoformat() if job.requested_at else None,
        "frozen_at": job.frozen_at.isoformat() if job.frozen_at else None,
        "approved_at": job.approved_at.isoformat() if job.approved_at else None,
        "terraform_applied_at": job.terraform_applied_at.isoformat()
        if job.terraform_applied_at
        else None,
        "aws_verified_at": job.aws_verified_at.isoformat() if job.aws_verified_at else None,
        "runtime_cleaned_at": job.runtime_cleaned_at.isoformat()
        if job.runtime_cleaned_at
        else None,
        "data_cleaned_at": job.data_cleaned_at.isoformat() if job.data_cleaned_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


def _to_detail(job: TenantDecommissionJob) -> dict:
    data = _to_summary(job)
    data.update(
        {
            "resource_snapshot": job.resource_snapshot,
            "dependency_snapshot": job.dependency_snapshot,
            "verification_results": job.verification_results,
            "terraform_plan_summary": job.terraform_plan_summary,
        }
    )
    return data


def _to_event(event: TenantDecommissionEvent) -> dict:
    return {
        "id": event.id,
        "step": event.step,
        "status": event.status,
        "actor_type": event.actor_type,
        "actor_id": event.actor_id,
        "correlation_id": event.correlation_id,
        "safe_details": event.safe_details,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


@router.post(
    "/admin/tenants/{tenant_id}/decommission/preview",
    response_model=DecommissionPreviewResponse,
)
async def preview_decommission(
    tenant_id: int,
    payload: DecommissionPreviewRequest,
    context: RequestContext = Depends(require_human_platform_admin),
    session: AsyncSession = Depends(get_db),
) -> dict:
    svc = TenantDecommissionService(session)
    try:
        return await svc.preview(tenant_id, payload.reason)
    except DecommissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": exc.message, "code": exc.code},
        ) from exc


def _require_aal2(context: RequestContext) -> None:
    if context.aal not in ("aal2", "aal3"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Decommission requires AAL2/2FA authentication.",
        )


@router.post(
    "/admin/tenants/{tenant_id}/decommission",
    response_model=DecommissionJobDetail,
    status_code=status.HTTP_201_CREATED,
)
async def request_decommission(
    tenant_id: int,
    payload: DecommissionRequest,
    context: RequestContext = Depends(require_human_platform_admin),
    session: AsyncSession = Depends(get_db),
) -> dict:
    _require_aal2(context)
    svc = TenantDecommissionService(session)
    app_sha, infra_sha = _sha()
    try:
        job = await svc.request(
            tenant_id=tenant_id,
            reason=payload.reason,
            confirmation=payload.confirmation,
            idempotency_key=payload.idempotency_key,
            requested_by=context.user_id,
            application_sha=app_sha,
            infrastructure_sha=infra_sha,
        )
        await session.commit()
        return _to_detail(job)
    except DecommissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": exc.message, "code": exc.code},
        ) from exc


@router.get("/admin/tenant-decommissions/{job_id}", response_model=DecommissionJobDetail)
async def get_decommission_job(
    job_id: str,
    context: RequestContext = Depends(require_human_platform_admin),
    session: AsyncSession = Depends(get_db),
) -> dict:
    svc = TenantDecommissionService(session)
    try:
        job = await svc._get_job(job_id)
    except DecommissionError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message) from exc
    return _to_detail(job)


@router.get(
    "/admin/tenant-decommissions/{job_id}/events",
    response_model=list[DecommissionEventRead],
)
async def get_decommission_events(
    job_id: str,
    context: RequestContext = Depends(require_human_platform_admin),
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    from sqlalchemy import select

    from app.models.tenant_decommission import TenantDecommissionEvent

    rows = (
        await session.scalars(
            select(TenantDecommissionEvent)
            .where(TenantDecommissionEvent.job_id == job_id)
            .order_by(TenantDecommissionEvent.created_at)
        )
    ).all()
    return [_to_event(r) for r in rows]


@router.post(
    "/admin/tenant-decommissions/{job_id}/approve",
    response_model=DecommissionJobDetail,
)
async def approve_decommission(
    job_id: str,
    payload: DecommissionApproveRequest,
    context: RequestContext = Depends(require_human_platform_admin),
    session: AsyncSession = Depends(get_db),
) -> dict:
    _require_aal2(context)
    svc = TenantDecommissionService(session)
    try:
        job = await svc.approve(
            job_id=job_id,
            approved_by=context.user_id,
            confirmation=payload.confirmation,
            plan_sha256=payload.plan_sha256,
        )
        await session.commit()
        return _to_detail(job)
    except DecommissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": exc.message, "code": exc.code},
        ) from exc


@router.post(
    "/admin/tenant-decommissions/{job_id}/retry",
    response_model=DecommissionRetryResponse,
)
async def retry_decommission(
    job_id: str,
    context: RequestContext = Depends(require_human_platform_admin),
    session: AsyncSession = Depends(get_db),
) -> dict:
    svc = TenantDecommissionService(session)
    try:
        job = await svc.retry(job_id, context.user_id)
        await session.commit()
        return {
            "job_id": job.id,
            "status": job.status,
            "current_step": job.current_step,
            "message": "Retry accepted.",
        }
    except DecommissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": exc.message, "code": exc.code},
        ) from exc


@router.post(
    "/admin/tenant-decommissions/{job_id}/cancel",
    response_model=DecommissionJobDetail,
)
async def cancel_decommission(
    job_id: str,
    context: RequestContext = Depends(require_human_platform_admin),
    session: AsyncSession = Depends(get_db),
) -> dict:
    svc = TenantDecommissionService(session)
    try:
        job = await svc.cancel(job_id, context.user_id)
        await session.commit()
        return _to_detail(job)
    except DecommissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": exc.message, "code": exc.code},
        ) from exc


@router.post(
    "/admin/tenant-decommissions/{job_id}/unfreeze",
    response_model=DecommissionJobDetail,
)
async def unfreeze_decommission(
    job_id: str,
    context: RequestContext = Depends(require_human_platform_admin),
    session: AsyncSession = Depends(get_db),
) -> dict:
    svc = TenantDecommissionService(session)
    try:
        job = await svc.unfreeze(job_id, context.user_id)
        await session.commit()
        return _to_detail(job)
    except DecommissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": exc.message, "code": exc.code},
        ) from exc


@router.post(
    "/admin/tenant-decommissions/{job_id}/runner-callback",
    response_model=DecommissionJobDetail,
)
async def runner_callback(
    job_id: str,
    payload: DecommissionRunnerCallback,
    context: RequestContext = Depends(require_human_platform_admin),
    session: AsyncSession = Depends(get_db),
) -> dict:
    # In production this should be guarded by a runner-only API key / signed
    # workload-identity token. It is intentionally under the same admin router
    # so the policy is uniform.
    svc = TenantDecommissionService(session)
    try:
        job = await svc.runner_callback(
            job_id=job_id,
            step=payload.step,
            status=payload.status,
            actor_id=str(context.user_id) if context.user_id else "runner",
            safe_details=payload.safe_details,
            error_code=payload.error_code,
            error_message_safe=payload.error_message_safe,
        )
        await session.commit()
        return _to_detail(job)
    except DecommissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": exc.message, "code": exc.code},
        ) from exc
