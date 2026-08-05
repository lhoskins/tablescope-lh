"""Reference Library — per-project views and assignment actions.

Split from ``reference_library.py``; siblings:
``reference_library_documents.py`` and ``reference_library_suggestions.py``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.reference_library import (
    TIER_COMPANY,
    TIER_INDUSTRY,
    TIER_PROJECT,
    ReferenceDocument,
    ReferenceDocumentAssignment,
)
from app.routes.reference_library_documents import _project_read_access
from app.services.reference_library_service import can_write_tier

router = APIRouter(prefix="/reference-library", tags=["reference-library"])


# ── project library (inherited / suggested / project-unique) ─────────────────


@router.get("/project/{project_id}")
async def project_library(
    project_id: int,
    context: RequestContext = Depends(require_role(Role.VIEWER)),
    session: AsyncSession = Depends(get_db),
) -> dict:
    await _project_read_access(session, context, project_id)

    # Assignments for this project.
    assignments = (
        await session.scalars(
            select(ReferenceDocumentAssignment).where(
                ReferenceDocumentAssignment.project_id == project_id
            )
        )
    ).all()
    excluded_doc_ids = {
        a.reference_document_id
        for a in assignments
        if a.assignment_type == "inherited" and not a.is_active
    }
    added_doc_ids = {
        a.reference_document_id
        for a in assignments
        if a.assignment_type == "manually_added" and a.is_active
    }
    suggested = [
        a
        for a in assignments
        if a.assignment_type == "suggested" and a.suggestion_status == "pending"
    ]

    # Inherited: company docs (this tenant) flagged inherit_default, minus exclusions.
    company_inherited = (
        await session.scalars(
            select(ReferenceDocument).where(
                ReferenceDocument.tier == TIER_COMPANY,
                ReferenceDocument.tenant_id == context.tenant_id,
                ReferenceDocument.inherit_default.is_(True),
            )
        )
    ).all()
    inherited_docs = [d for d in company_inherited if d.id not in excluded_doc_ids]

    # Manually-added (approved suggestions) industry/company docs.
    if added_doc_ids:
        added_docs = (
            await session.scalars(
                select(ReferenceDocument).where(ReferenceDocument.id.in_(added_doc_ids))
            )
        ).all()
    else:
        added_docs = []

    # Project-unique docs.
    project_unique = (
        await session.scalars(
            select(ReferenceDocument)
            .where(
                ReferenceDocument.tier == TIER_PROJECT,
                ReferenceDocument.project_id == project_id,
            )
            .order_by(ReferenceDocument.title)
        )
    ).all()

    # Resolve suggested docs.
    suggested_out = []
    for a in suggested:
        d = await session.get(ReferenceDocument, a.reference_document_id)
        if d is not None:
            entry = d.to_dict()
            entry["assignmentId"] = a.id
            entry["reasoning"] = a.reasoning
            suggested_out.append(entry)

    def _tag(d: ReferenceDocument) -> dict:
        e = d.to_dict()
        e["tierBadge"] = "Company" if d.tier == TIER_COMPANY else (
            "Industry" if d.tier == TIER_INDUSTRY else "Project"
        )
        return e

    inherited_out = [_tag(d) for d in inherited_docs] + [_tag(d) for d in added_docs]

    total_active = len(inherited_out) + len(project_unique)
    return {
        "inherited": inherited_out,
        "suggested": suggested_out,
        "projectUnique": [d.to_dict() for d in project_unique],
        "summary": {
            "inherited": len(inherited_out),
            "suggested": len(suggested_out),
            "suggestedPending": len(suggested_out),
            "projectUnique": len(project_unique),
            "totalActive": total_active,
        },
    }


# ── assignment actions ───────────────────────────────────────────────────────


@router.post("/assignments/{assignment_id}/approve")
async def approve_suggestion(
    assignment_id: int,
    context: RequestContext = Depends(require_role(Role.VIEWER)),
    session: AsyncSession = Depends(get_db),
) -> dict:
    a = await session.get(ReferenceDocumentAssignment, assignment_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Assignment not found")
    await _project_write(session, context, a.project_id)
    a.suggestion_status = "approved"
    a.assignment_type = "manually_added"
    a.is_active = True
    a.added_by = context.user_id
    await session.commit()
    return a.to_dict()


@router.post("/assignments/{assignment_id}/dismiss")
async def dismiss_suggestion(
    assignment_id: int,
    context: RequestContext = Depends(require_role(Role.VIEWER)),
    session: AsyncSession = Depends(get_db),
) -> dict:
    a = await session.get(ReferenceDocumentAssignment, assignment_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Assignment not found")
    await _project_write(session, context, a.project_id)
    a.suggestion_status = "dismissed"
    a.is_active = False
    await session.commit()
    return a.to_dict()


async def _project_write(
    session: AsyncSession, context: RequestContext, project_id: int
) -> None:
    if not await can_write_tier(session, context, TIER_PROJECT, project_id):
        raise HTTPException(status_code=403, detail="Not permitted for this project")


@router.post("/project/{project_id}/documents/{document_id}/remove")
async def remove_inherited(
    project_id: int,
    document_id: int,
    context: RequestContext = Depends(require_role(Role.VIEWER)),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Exclude an inherited doc from this project's AI scope (override, reversible)."""
    await _project_write(session, context, project_id)
    existing = await session.scalar(
        select(ReferenceDocumentAssignment).where(
            ReferenceDocumentAssignment.project_id == project_id,
            ReferenceDocumentAssignment.reference_document_id == document_id,
            ReferenceDocumentAssignment.assignment_type == "inherited",
        )
    )
    if existing is None:
        existing = ReferenceDocumentAssignment(
            reference_document_id=document_id,
            project_id=project_id,
            assignment_type="inherited",
            is_active=False,
            added_by=context.user_id,
        )
        session.add(existing)
    else:
        existing.is_active = False
    await session.commit()
    return {"status": "removed"}


@router.post("/project/{project_id}/documents/{document_id}/add")
async def readd_inherited(
    project_id: int,
    document_id: int,
    context: RequestContext = Depends(require_role(Role.VIEWER)),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Re-include a previously removed inherited doc."""
    await _project_write(session, context, project_id)
    existing = await session.scalar(
        select(ReferenceDocumentAssignment).where(
            ReferenceDocumentAssignment.project_id == project_id,
            ReferenceDocumentAssignment.reference_document_id == document_id,
            ReferenceDocumentAssignment.assignment_type == "inherited",
        )
    )
    if existing is not None:
        existing.is_active = True
        await session.commit()
    return {"status": "added"}
