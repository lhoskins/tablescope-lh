"""Reference Library — document CRUD, downloads, and the company-tier view.

Split from ``reference_library.py``; siblings:
``reference_library_project_views.py`` and ``reference_library_suggestions.py``.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.audit_event import AuditEvent
from app.models.project import Project, ProjectMember
from app.models.reference_library import (
    DOMAIN_TAGS,
    TIER_COMPANY,
    TIER_INDUSTRY,
    TIER_PROJECT,
    ReferenceDocument,
    ReferenceDocumentAssignment,
)
from app.services.presentation_engine import PresentationMode
from app.services.reference_library_processing import (
    EXT_TO_FILE_TYPE,
    EXTRACTABLE_EXTENSIONS,
    process_reference_document,
    store_reference_file,
)
from app.services.reference_library_service import (
    can_write_company,
    can_write_industry,
    can_write_tier,
    find_duplicate_in_tier,
    normalize_domain_tag,
)
from app.services.response_envelope import attach_envelope

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/reference-library", tags=["reference-library"])

MAX_FILE_BYTES = 50 * 1024 * 1024  # 50 MB (single upload limit)

KNOWN_ISSUERS = [
    "NIST", "ISO", "FAR/GSA", "GSA", "DoD", "AICPA", "SEC", "FASB", "IFRS Foundation",
    "OSHA", "EPA", "FDA", "HHS", "PCI SSC", "CISA", "OWASP", "IEEE", "INCOSE",
    "SHRM", "GRI", "SASB", "TCFD", "FTC", "IATF", "SAE", "PCAOB",
]


# ── helpers ──────────────────────────────────────────────────────────────────


async def _project_read_access(
    session: AsyncSession, context: RequestContext, project_id: int
) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.tenant_id != context.tenant_id:
        raise HTTPException(status_code=403, detail="Not in this tenant")
    # tenant admins can read any project in the tenant; others must be members
    from app.auth.rbac import has_role

    if has_role(context.role, Role.TENANT_ADMIN):
        return project
    member = await session.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == context.user_id,
        )
    )
    if member is None:
        raise HTTPException(status_code=403, detail="Not a member of this project")
    return project


def _audit(
    session: AsyncSession,
    context: RequestContext,
    *,
    event_type: str,
    title: str | None = None,
    project_id: int | None = None,
    documents: list | None = None,
) -> None:
    session.add(
        AuditEvent(
            tenant_id=context.tenant_id,
            project_id=project_id,
            user_id=context.user_id,
            event_type=event_type,
            scope="reference_library",
            title=title,
            documents_read=documents or [],
        )
    )


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


@router.get("/meta")
async def get_meta(
    context: RequestContext = Depends(require_role(Role.VIEWER)),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Static metadata + the current user's write permissions per tier."""
    return {
        "domains": list(DOMAIN_TAGS),
        "issuers": KNOWN_ISSUERS,
        "applicabilityTags": [
            "Federal", "Federal/Defense", "Industry", "Global", "State",
            "Company-specific",
        ],
        "permissions": {
            "industryWrite": can_write_industry(context),
            "companyWrite": can_write_company(context),
        },
    }


# ── list / get documents ─────────────────────────────────────────────────────


@router.get("/documents")
async def list_documents(
    tier: str = Query(...),
    project_id: int | None = Query(None),
    domain: str | None = Query(None),
    search: str | None = Query(None),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """List reference documents in a tier (scoped + permission-checked)."""
    stmt = select(ReferenceDocument).where(ReferenceDocument.tier == tier)

    if tier == TIER_INDUSTRY:
        pass  # readable by all authenticated users
    elif tier == TIER_COMPANY:
        stmt = stmt.where(ReferenceDocument.tenant_id == context.tenant_id)
    elif tier == TIER_PROJECT:
        if project_id is None:
            raise HTTPException(status_code=400, detail="project_id required for project tier")
        await _project_read_access(session, context, project_id)
        stmt = stmt.where(ReferenceDocument.project_id == project_id)
    else:
        raise HTTPException(status_code=400, detail="Invalid tier")

    if domain:
        stmt = stmt.where(ReferenceDocument.domain_tag == domain)
    if search:
        like = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                ReferenceDocument.title.ilike(like),
                ReferenceDocument.issuing_body.ilike(like),
            )
        )
    stmt = stmt.order_by(ReferenceDocument.domain_tag, ReferenceDocument.title)
    docs = (await session.scalars(stmt)).all()
    return {"documents": [d.to_dict() for d in docs]}


async def _get_doc_with_read_access(
    session: AsyncSession, context: RequestContext, document_id: int
) -> ReferenceDocument:
    doc = await session.get(ReferenceDocument, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Reference document not found")
    if doc.tier == TIER_COMPANY and doc.tenant_id != context.tenant_id:
        raise HTTPException(status_code=403, detail="Not in this tenant")
    if doc.tier == TIER_PROJECT and doc.project_id is not None:
        await _project_read_access(session, context, doc.project_id)
    return doc


@router.get("/documents/{document_id}")
async def get_document(
    document_id: int,
    context: RequestContext = Depends(require_role(Role.VIEWER)),
    session: AsyncSession = Depends(get_db),
) -> dict:
    doc = await _get_doc_with_read_access(session, context, document_id)
    payload = doc.to_dict()
    attach_envelope(
        payload,
        PresentationMode.DOCUMENT,
        summary=doc.ai_summary or None,
        status=doc.status or None,
    )
    return payload


@router.get("/documents/{document_id}/detail")
async def get_document_detail(
    document_id: int,
    context: RequestContext = Depends(require_role(Role.VIEWER)),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Full detail for a reference document: metadata + AI summary, its version
    (supersede) family, and where it is used across projects."""
    doc = await _get_doc_with_read_access(session, context, document_id)

    # ── version family: walk the supersede lineage in both directions ──
    family_ids: set[int] = {doc.id}
    cur: ReferenceDocument | None = doc
    seen: set[int] = set()
    while cur is not None and cur.id not in seen:
        seen.add(cur.id)
        family_ids.add(cur.id)
        if cur.superseded_by_id is None:
            break
        cur = await session.get(ReferenceDocument, cur.superseded_by_id)
    for _ in range(10):  # bounded backward expansion over predecessors
        preds = (
            await session.scalars(
                select(ReferenceDocument.id).where(
                    ReferenceDocument.superseded_by_id.in_(family_ids)
                )
            )
        ).all()
        new_ids = set(preds) - family_ids
        if not new_ids:
            break
        family_ids |= new_ids

    fam_rows = (
        await session.scalars(
            select(ReferenceDocument).where(ReferenceDocument.id.in_(family_ids))
        )
    ).all()
    version_family = sorted(
        (
            {
                "id": d.id,
                "title": d.title,
                "versionLabel": d.version_label,
                "status": d.status,
                "effectiveDate": d.effective_date.isoformat() if d.effective_date else None,
                "isCurrent": d.id == doc.id,
                "supersededById": d.superseded_by_id,
            }
            for d in fam_rows
        ),
        key=lambda r: (r["effectiveDate"] or "", r["id"]),
    )

    # ── usage: projects that inherit / use this reference ──
    usage: list[dict] = []
    if doc.tier in (TIER_COMPANY, TIER_INDUSTRY):
        rows = (
            await session.execute(
                select(ReferenceDocumentAssignment, Project.name)
                .join(Project, Project.id == ReferenceDocumentAssignment.project_id)
                .where(
                    ReferenceDocumentAssignment.reference_document_id == doc.id,
                    ReferenceDocumentAssignment.is_active.is_(True),
                )
            )
        ).all()
        usage = [
            {
                "projectId": a.project_id,
                "projectName": name,
                "assignmentType": a.assignment_type,
                "suggestionStatus": a.suggestion_status,
            }
            for a, name in rows
        ]

    return {
        "document": doc.to_dict(),
        "versionFamily": version_family,
        "usage": usage,
    }


@router.get("/documents/{document_id}/download")
async def download_document(
    document_id: int,
    context: RequestContext = Depends(require_role(Role.VIEWER)),
    session: AsyncSession = Depends(get_db),
) -> FileResponse:
    doc = await _get_doc_with_read_access(session, context, document_id)
    if not doc.file_path or not Path(doc.file_path).exists():
        raise HTTPException(status_code=404, detail="No file available for this document")
    filename = doc.original_filename or f"{doc.title}.{doc.file_type or 'bin'}"
    return FileResponse(doc.file_path, filename=filename)


# ── create / upload ──────────────────────────────────────────────────────────


@router.post("/documents")
async def create_document(
    background_tasks: BackgroundTasks,
    tier: str = Form(...),
    title: str = Form(...),
    issuing_body: str | None = Form(None),
    domain_tag: str | None = Form(None),
    applicability_tag: str | None = Form(None),
    source_url: str | None = Form(None),
    effective_date: str | None = Form(None),
    version_label: str | None = Form(None),
    project_id: int | None = Form(None),
    assignment_type: str | None = Form(None),
    existing_document_id: int | None = Form(None),
    override_duplicate: bool = Form(False),
    file: UploadFile | None = File(None),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Create (or fill a stub for) a reference document and start processing."""
    if tier not in (TIER_INDUSTRY, TIER_COMPANY, TIER_PROJECT):
        raise HTTPException(status_code=400, detail="Invalid tier")
    if not await can_write_tier(session, context, tier, project_id):
        raise HTTPException(status_code=403, detail="Not permitted to write to this tier")
    if tier == TIER_PROJECT:
        if project_id is None:
            raise HTTPException(status_code=400, detail="project_id required for project tier")
        await _project_read_access(session, context, project_id)

    domain, _ = normalize_domain_tag(domain_tag)

    # Duplicate detection (unless filling a known stub or overriding).
    if existing_document_id is None and not override_duplicate:
        dup = await find_duplicate_in_tier(
            session,
            tier=tier,
            title=title,
            tenant_id=context.tenant_id if tier == TIER_COMPANY else None,
            project_id=project_id if tier == TIER_PROJECT else None,
        )
        if dup is not None and dup.file_path:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Possible duplicate of an existing reference",
                    "existingId": dup.id,
                    "existingTitle": dup.title,
                },
            )
        if dup is not None and not dup.file_path:
            # Matches a metadata-only stub → fill it instead of duplicating.
            existing_document_id = dup.id

    # Resolve target document (new or existing stub).
    if existing_document_id is not None:
        doc = await session.get(ReferenceDocument, existing_document_id)
        if doc is None or doc.tier != tier:
            raise HTTPException(status_code=404, detail="Existing reference not found")
        doc.title = title
        doc.issuing_body = issuing_body or doc.issuing_body
        doc.domain_tag = domain
        doc.applicability_tag = applicability_tag or doc.applicability_tag
        doc.source_url = source_url or doc.source_url
        doc.version_label = version_label or doc.version_label
        if effective_date:
            doc.effective_date = _parse_date(effective_date)
    else:
        doc = ReferenceDocument(
            tier=tier,
            tenant_id=context.tenant_id if tier in (TIER_COMPANY, TIER_PROJECT) else None,
            project_id=project_id if tier == TIER_PROJECT else None,
            title=title,
            issuing_body=issuing_body,
            domain_tag=domain,
            applicability_tag=applicability_tag,
            source_url=source_url,
            effective_date=_parse_date(effective_date),
            version_label=version_label,
            status="draft",
            uploaded_by=context.user_id,
        )
        session.add(doc)
    await session.flush()

    # Handle file (optional — stubs can be metadata-only).
    has_file = file is not None and file.filename
    if has_file:
        assert file is not None
        ext = Path(file.filename or "").suffix.lower()
        if ext not in EXTRACTABLE_EXTENSIONS and ext != ".doc":
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {ext or '(none)'}. "
                "Allowed: pdf, docx, pptx, txt, md, html",
            )
        data = await file.read()
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(status_code=400, detail="File exceeds 50MB limit")
        path = store_reference_file(
            tier=tier,
            domain_tag=domain,
            tenant_id=doc.tenant_id,
            project_id=doc.project_id,
            document_id=doc.id,
            ext=ext,
            data=data,
        )
        doc.file_path = path
        doc.file_type = EXT_TO_FILE_TYPE.get(ext, ext.lstrip("."))
        doc.file_size_bytes = len(data)
        doc.original_filename = file.filename
        doc.status = "processing"

    # Project-tier assignment row (project-unique vs suggest-promote).
    if tier == TIER_PROJECT and project_id is not None and existing_document_id is None:
        atype = "project_unique"
        session.add(
            ReferenceDocumentAssignment(
                reference_document_id=doc.id,
                project_id=project_id,
                assignment_type=atype,
                added_by=context.user_id,
            )
        )

    _audit(
        session,
        context,
        event_type="reference_library_upload",
        title=doc.title,
        project_id=doc.project_id,
        documents=[doc.id],
    )
    await session.commit()

    if has_file:
        background_tasks.add_task(process_reference_document, doc.id)

    return doc.to_dict()


# ── update / status ──────────────────────────────────────────────────────────


class UpdateDocumentBody(BaseModel):
    title: str | None = None
    issuing_body: str | None = None
    domain_tag: str | None = None
    applicability_tag: str | None = None
    source_url: str | None = None
    effective_date: str | None = None
    version_label: str | None = None
    ai_summary: str | None = None
    inherit_default: bool | None = None


@router.patch("/documents/{document_id}")
async def update_document(
    document_id: int,
    body: UpdateDocumentBody,
    context: RequestContext = Depends(require_role(Role.VIEWER)),
    session: AsyncSession = Depends(get_db),
) -> dict:
    doc = await session.get(ReferenceDocument, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Reference document not found")
    if not await can_write_tier(session, context, doc.tier, doc.project_id):
        raise HTTPException(status_code=403, detail="Not permitted to edit this document")
    if doc.tier == TIER_COMPANY and doc.tenant_id != context.tenant_id:
        raise HTTPException(status_code=403, detail="Not in this tenant")

    if body.title is not None:
        doc.title = body.title
    if body.issuing_body is not None:
        doc.issuing_body = body.issuing_body
    if body.domain_tag is not None:
        doc.domain_tag, _ = normalize_domain_tag(body.domain_tag)
    if body.applicability_tag is not None:
        doc.applicability_tag = body.applicability_tag
    if body.source_url is not None:
        doc.source_url = body.source_url
    if body.effective_date is not None:
        doc.effective_date = _parse_date(body.effective_date)
    if body.version_label is not None:
        doc.version_label = body.version_label
    if body.ai_summary is not None:
        doc.ai_summary = body.ai_summary
        if doc.status == "draft":
            doc.status = "active"
    if body.inherit_default is not None and doc.tier == TIER_COMPANY:
        doc.inherit_default = body.inherit_default

    await session.commit()
    return doc.to_dict()


@router.post("/documents/{document_id}/process")
async def reprocess_document(
    document_id: int,
    background_tasks: BackgroundTasks,
    context: RequestContext = Depends(require_role(Role.VIEWER)),
    session: AsyncSession = Depends(get_db),
) -> dict:
    doc = await session.get(ReferenceDocument, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Reference document not found")
    if not await can_write_tier(session, context, doc.tier, doc.project_id):
        raise HTTPException(status_code=403, detail="Not permitted")
    if not doc.file_path:
        raise HTTPException(status_code=400, detail="No file to process")
    doc.status = "processing"
    await session.commit()
    background_tasks.add_task(process_reference_document, doc.id)
    return {"status": "processing"}


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: int,
    context: RequestContext = Depends(require_role(Role.VIEWER)),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a reference document (and its stored file). Write-permission +
    tenant/project scoped. Assignment rows cascade; supersede links reset."""
    doc = await session.get(ReferenceDocument, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Reference document not found")
    if not await can_write_tier(session, context, doc.tier, doc.project_id):
        raise HTTPException(status_code=403, detail="Not permitted to delete this document")
    if doc.tier == TIER_COMPANY and doc.tenant_id != context.tenant_id:
        raise HTTPException(status_code=403, detail="Not in this tenant")

    for path in (doc.file_path, doc.extracted_text_path):
        if path:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                logger.warning("Could not remove file %s for reference doc %s", path, doc.id)

    _audit(
        session,
        context,
        event_type="reference_library_delete",
        title=doc.title,
        project_id=doc.project_id,
        documents=[doc.id],
    )
    await session.delete(doc)
    await session.commit()
    return {"status": "deleted"}


@router.post("/documents/{document_id}/supersede")
async def supersede_document(
    document_id: int,
    superseded_by_id: int | None = Query(None),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
    session: AsyncSession = Depends(get_db),
) -> dict:
    doc = await session.get(ReferenceDocument, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Reference document not found")
    if not await can_write_tier(session, context, doc.tier, doc.project_id):
        raise HTTPException(status_code=403, detail="Not permitted")
    doc.status = "superseded"
    doc.superseded_by_id = superseded_by_id
    await session.commit()
    return doc.to_dict()


# ── company library ──────────────────────────────────────────────────────────


@router.get("/company")
async def company_library(
    context: RequestContext = Depends(require_role(Role.TENANT_ADMIN)),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Company-tier library + stats for the caller's tenant (tenant admin only)."""
    docs = (
        await session.scalars(
            select(ReferenceDocument)
            .where(
                ReferenceDocument.tier == TIER_COMPANY,
                ReferenceDocument.tenant_id == context.tenant_id,
            )
            .order_by(ReferenceDocument.title)
        )
    ).all()
    by_domain: dict[str, int] = {}
    inherit_count = 0
    for d in docs:
        by_domain[d.domain_tag or "Other"] = by_domain.get(d.domain_tag or "Other", 0) + 1
        if d.inherit_default:
            inherit_count += 1
    return {
        "documents": [d.to_dict() for d in docs],
        "stats": {
            "total": len(docs),
            "byDomain": by_domain,
            "inheritByDefault": inherit_count,
        },
    }
