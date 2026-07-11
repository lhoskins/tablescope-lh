"""Reference Library API — three-tier reference documents.

Tiers: industry (platform staff write), company (tenant admin write), project
(project admin write). Reads are scoped by tenant/project and enforced here at
the data-access layer, not just in the UI.
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
    ReferenceAdditionRequest,
    ReferenceDocument,
    ReferenceDocumentAssignment,
)
from app.services import reference_library_ai_client as suggest_client
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


# ── meta ─────────────────────────────────────────────────────────────────────


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
