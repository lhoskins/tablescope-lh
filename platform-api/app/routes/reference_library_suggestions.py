"""Reference Library — AI suggestion engine and catalog addition requests.

Split from ``reference_library.py``; siblings:
``reference_library_documents.py`` and ``reference_library_project_views.py``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.reference_library import (
    DOMAIN_TAGS,
    TIER_INDUSTRY,
    ReferenceAdditionRequest,
    ReferenceDocument,
    ReferenceDocumentAssignment,
)
from app.routes.reference_library_documents import _audit, _project_read_access
from app.services import reference_library_ai_client as suggest_client

router = APIRouter(prefix="/reference-library", tags=["reference-library"])


# ── suggestion engine ────────────────────────────────────────────────────────


@router.post("/suggestions/generate")
async def generate_suggestions(
    project_id: int = Query(...),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Scan a project's signals and create Industry-reference suggestions."""
    from app.models.database_data_source import DatabaseDataSource
    from app.models.project_asset import ProjectAsset
    from app.models.saved_query import SavedQuery

    await _project_read_access(session, context, project_id)

    # Gather signals (best-effort).
    ds_rows = (
        await session.scalars(
            select(DatabaseDataSource).where(DatabaseDataSource.project_id == project_id)
        )
    ).all()
    data_source_types = sorted({(r.source_type or "") for r in ds_rows if r.source_type})
    table_names = sorted({r.display_name for r in ds_rows if r.display_name})[:80]
    asset_rows = (
        await session.scalars(
            select(ProjectAsset.asset_type).where(ProjectAsset.project_id == project_id)
        )
    ).all()
    document_types = sorted({a for a in asset_rows if a})
    query_rows = (
        await session.scalars(
            select(SavedQuery.name).where(SavedQuery.project_id == project_id)
        )
    ).all()
    recent_query_topics = [q for q in query_rows if q][:40]

    suggestions = await suggest_client.suggest_references(
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        project_id=project_id,
        data_source_types=data_source_types,
        table_names=table_names,
        document_types=document_types,
        recent_query_topics=recent_query_topics,
        candidate_domains=list(DOMAIN_TAGS),
    )
    if suggestions is None:
        raise HTTPException(status_code=503, detail="AI suggestion service unavailable")

    # Existing scope: doc ids already inherited/added/suggested/project-unique.
    existing_assignments = (
        await session.scalars(
            select(ReferenceDocumentAssignment.reference_document_id).where(
                ReferenceDocumentAssignment.project_id == project_id
            )
        )
    ).all()
    in_scope = set(existing_assignments)

    created = 0
    for s in suggestions:
        domain = s.get("domainTag")
        reasoning = s.get("reasoning", "")
        if not domain:
            continue
        # Top industry docs in that domain not already in scope.
        domain_docs = (
            await session.scalars(
                select(ReferenceDocument)
                .where(
                    ReferenceDocument.tier == TIER_INDUSTRY,
                    ReferenceDocument.domain_tag == domain,
                )
                .limit(5)
            )
        ).all()
        for d in domain_docs:
            if d.id in in_scope:
                continue
            session.add(
                ReferenceDocumentAssignment(
                    reference_document_id=d.id,
                    project_id=project_id,
                    assignment_type="suggested",
                    suggestion_status="pending",
                    reasoning=reasoning,
                    is_active=True,
                    added_by=context.user_id,
                )
            )
            in_scope.add(d.id)
            created += 1

    _audit(
        session,
        context,
        event_type="reference_library_suggestions_generated",
        project_id=project_id,
        title=f"{created} suggestions",
    )
    await session.commit()
    return {"created": created}


# ── request addition ─────────────────────────────────────────────────────────


class AdditionRequestBody(BaseModel):
    title: str
    issuing_body: str | None = None
    source_url: str | None = None
    domain_tag: str | None = None
    justification: str | None = None


@router.post("/requests")
async def create_addition_request(
    body: AdditionRequestBody,
    context: RequestContext = Depends(require_role(Role.TENANT_ADMIN)),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Tenant admin requests a standard be added to the shared Industry catalog."""
    req = ReferenceAdditionRequest(
        tenant_id=context.tenant_id,
        requested_by=context.user_id,
        title=body.title,
        issuing_body=body.issuing_body,
        source_url=body.source_url,
        domain_tag=body.domain_tag,
        justification=body.justification,
        status="pending",
    )
    session.add(req)
    await session.commit()
    return {"success": True, "id": req.id}


@router.get("/requests")
async def list_addition_requests(
    context: RequestContext = Depends(require_role(Role.ROOT_ADMIN)),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Platform-staff review queue for addition requests."""
    rows = (
        await session.scalars(
            select(ReferenceAdditionRequest).order_by(
                ReferenceAdditionRequest.created_at.desc()
            )
        )
    ).all()
    return {"requests": [r.to_dict() for r in rows]}