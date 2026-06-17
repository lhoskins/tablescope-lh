"""Live Report Builder — save/load shareable reports (query defs, not data).

Reports store the *definition* of each section (the insight card's query/prompt
metadata), never a snapshot of data. The viewer page re-executes each section's
suite on open, subject to the viewer's own project access — so data stays live
and project isolation is preserved.
"""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.report import Report

router = APIRouter(prefix="/reports", tags=["Reports"])


class ReportCreate(BaseModel):
    title: str = "Untitled report"
    sections: list[dict[str, Any]] = []
    share_settings: dict[str, Any] = {}


class ReportUpdate(BaseModel):
    title: str | None = None
    sections: list[dict[str, Any]] | None = None
    share_settings: dict[str, Any] | None = None


def _serialize(report: Report) -> dict[str, Any]:
    return {
        "id": report.id,
        "shareToken": report.share_token,
        "shareUrl": f"/reports/{report.share_token}",
        "title": report.title,
        "sections": report.sections or [],
        "shareSettings": report.share_settings or {},
        "createdAt": report.created_at.isoformat() if report.created_at else None,
        "updatedAt": report.updated_at.isoformat() if report.updated_at else None,
    }


@router.get("")
async def list_reports(
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> list[dict[str, Any]]:
    rows = await session.scalars(
        select(Report)
        .where(
            Report.tenant_id == context.tenant_id,
            Report.owner_id == context.user_id,
        )
        .order_by(Report.updated_at.desc())
    )
    return [_serialize(r) for r in rows]


@router.post("")
async def create_report(
    body: ReportCreate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    report = Report(
        tenant_id=context.tenant_id,
        owner_id=context.user_id,
        share_token=secrets.token_urlsafe(12),
        title=body.title or "Untitled report",
        sections=body.sections,
        share_settings=body.share_settings,
    )
    session.add(report)
    await session.commit()
    await session.refresh(report)
    return _serialize(report)


@router.get("/{share_token}")
async def get_report(
    share_token: str,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> dict[str, Any]:
    report = await session.scalar(
        select(Report).where(
            Report.share_token == share_token,
            Report.tenant_id == context.tenant_id,
        )
    )
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return _serialize(report)


@router.patch("/{share_token}")
async def update_report(
    share_token: str,
    body: ReportUpdate,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    report = await session.scalar(
        select(Report).where(
            Report.share_token == share_token,
            Report.tenant_id == context.tenant_id,
        )
    )
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if report.owner_id != context.user_id:
        raise HTTPException(status_code=403, detail="Not the report owner")
    if body.title is not None:
        report.title = body.title
    if body.sections is not None:
        report.sections = body.sections
    if body.share_settings is not None:
        report.share_settings = body.share_settings
    await session.commit()
    await session.refresh(report)
    return _serialize(report)


@router.delete("/{share_token}", status_code=204, response_class=Response)
async def delete_report(
    share_token: str,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> Response:
    report = await session.scalar(
        select(Report).where(
            Report.share_token == share_token,
            Report.tenant_id == context.tenant_id,
        )
    )
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if report.owner_id != context.user_id:
        raise HTTPException(status_code=403, detail="Not the report owner")
    await session.delete(report)
    await session.commit()
    return Response(status_code=204)
