"""File analysis API routes — AI-assisted upload analysis and metadata management."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models.file_source_meta import FileSourceMeta
from app.services import data_source_metadata_service as metadata_svc
from app.services.ai_file_analysis_service import analyze_file_with_ai
from app.services.file_profile_service import profile_uploaded_file
from app.services.upload_ai_profiler_service import (
    profile_uploaded_file as catalog_profile_file,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/data-sources", tags=["file-analysis"])

# In-memory store for upload sessions (keyed by session_id).
# For MVP this is sufficient; production would use Redis or DB.
_upload_sessions: dict[str, dict[str, Any]] = {}


@router.post("/upload/analyze")
async def analyze_upload(
    file: UploadFile = File(...),
    project_id: int | None = Form(None),
    source_name: str | None = Form(None),
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Upload a file, profile it, and run AI analysis.

    Returns the profile and AI analysis without finalizing the data source.
    The caller uses the upload_session_id to finalize later.
    """
    if file.filename is None:
        raise HTTPException(status_code=400, detail="Filename is required")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="File is empty")

    file_name = file.filename
    file_type = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else "csv"

    # Profile the file
    try:
        file_profile = profile_uploaded_file(content, file_name, file_type)
    except Exception as e:
        logger.error("File profiling failed: %s", e)
        raise HTTPException(status_code=422, detail=f"Could not parse file: {e}") from e

    if file_profile["column_count"] == 0:
        raise HTTPException(status_code=422, detail="No columns detected in file")

    # Run AI analysis (pass tenant/user/project context for the /ai/ask fallback)
    ai_result = await analyze_file_with_ai(
        file_profile,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        project_id=project_id or 0,
    )

    # Run catalog-based profiling (governed tags + KPIs)
    columns_for_catalog = [
        {"name": f["field_name"], "type": f.get("detected_type", "string")}
        for f in file_profile.get("fields", [])
    ]
    catalog_result = await catalog_profile_file(
        session=session,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        project_id=project_id or 0,
        source_id=0,
        view_name=file_name.rsplit(".", 1)[0] if "." in file_name else file_name,
        file_name=file_name,
        columns=columns_for_catalog,
        sample_rows=file_profile.get("sample_rows", []),
        persist=False,  # Don't persist yet — finalize will persist with real IDs
    )

    # Store in upload session
    session_id = str(uuid.uuid4())
    _upload_sessions[session_id] = {
        "content": content,
        "file_name": file_name,
        "file_type": file_type,
        "source_name": source_name,
        "project_id": project_id,
        "tenant_id": context.tenant_id,
        "user_id": context.user_id,
        "file_profile": file_profile,
        "ai_result": ai_result,
        "catalog_result": catalog_result,
    }

    return {
        "upload_session_id": session_id,
        "file": {
            "file_name": file_profile["file_name"],
            "file_type": file_profile["file_type"],
            "file_size_bytes": file_profile["file_size_bytes"],
            "row_count": file_profile["row_count"],
            "column_count": file_profile["column_count"],
            "sheet_name": file_profile.get("sheet_name"),
        },
        "summary": {
            "ai_summary": catalog_result.get("summary") or ai_result.get("summary", ""),
            "ai_usage_summary": ai_result.get("usage_summary", ""),
            "ai_quality_summary": ai_result.get("quality_summary", ""),
            "business_domain": catalog_result.get("business_domain", ""),
            "process_area": catalog_result.get("process_area", ""),
        },
        "fields": [
            {
                **pf,
                "ai_description": next(
                    (af["description"] for af in ai_result.get("fields", [])
                     if af["field_name"] == pf["field_name"]),
                    "",
                ),
                "ai_quality_notes": next(
                    (af["quality_notes"] for af in ai_result.get("fields", [])
                     if af["field_name"] == pf["field_name"]),
                    "",
                ),
            }
            for pf in file_profile["fields"]
        ],
        "tags": [
            {**t, "source": "catalog", "accepted": True}
            for t in catalog_result.get("suggested_tags", [])
        ] or [
            {**t, "source": "ai", "accepted": True}
            for t in ai_result.get("tags", [])
        ],
        "kpis": [
            {**k, "source": "catalog", "accepted": True}
            for k in catalog_result.get("suggested_kpis", [])
        ],
        "relationship_hints": catalog_result.get("relationship_hints", []),
        "data_quality_notes": catalog_result.get("data_quality_notes", []),
        "recommendations": [
            {**r, "client_id": f"rec_{i}", "status": "pending"}
            for i, r in enumerate(ai_result.get("recommendations", []))
        ],
        "status": "analysis_complete",
    }


class FinalizeRequest(BaseModel):
    upload_session_id: str
    project_id: int | None = None
    display_name: str | None = None
    accepted_tags: list[dict[str, Any]] | None = None
    accepted_tag_keys: list[str] | None = None
    rejected_tag_keys: list[str] | None = None
    accepted_kpi_keys: list[str] | None = None
    rejected_kpi_keys: list[str] | None = None
    recommendation_decisions: list[dict[str, Any]] | None = None
    user_notes: str | None = None
    user_nuances: str | None = None


@router.post("/upload/finalize")
async def finalize_upload(
    req: FinalizeRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Finalize the upload — create the data source and persist AI metadata.

    This endpoint:
    1. Forwards the file to Teiid (via the existing upload flow)
    2. Creates the FileSourceMeta record
    3. Persists the AI profile, field profiles, tags, and recommendations
    """
    upload_data = _upload_sessions.pop(req.upload_session_id, None)
    if upload_data is None:
        raise HTTPException(status_code=404, detail="Upload session not found or expired")

    content = upload_data["content"]
    file_name = upload_data["file_name"]
    file_profile = upload_data["file_profile"]
    ai_result = upload_data["ai_result"]
    project_id = req.project_id or upload_data.get("project_id")

    # Forward file to Teiid via the existing upload mechanism
    import httpx

    from app.models.project import Project
    from app.models.tenant import Tenant
    from app.models.user import User
    from app.services.file_sources import (
        compute_view_name,
        convert_to_csv_if_needed,
        detect_column_types,
        sanitize_csv_content,
        sanitize_filename,
        sanitize_xlsx_content,
    )
    from app.services.tenant_teiid_resolver import TenantTeiidResolver

    user = await session.get(User, context.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    tenant = await session.get(Tenant, context.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    clean_name = sanitize_filename(file_name)
    lower_name = clean_name.lower()
    if lower_name.endswith((".csv", ".tsv", ".txt")):
        content = sanitize_csv_content(content)
    elif lower_name.endswith((".xlsx", ".xlsm", ".xls")):
        content = sanitize_xlsx_content(content)
        clean_name = clean_name.rsplit(".", 1)[0] + ".csv"

    original_format = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else None

    try:
        final_filename, content = convert_to_csv_if_needed(clean_name, content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    endpoint = await TenantTeiidResolver(session).resolve_for_org(context.tenant_id)
    servlet_url = f"{endpoint.servlet_url}/TeiidExcelImporterTest/upload"

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=10.0)
        ) as client:
            resp = await client.post(
                servlet_url,
                data={
                    "org_id": str(tenant.id),
                    "user_id": str(user.id),
                    "vdb_type": "user",
                    "replace": "true",
                },
                files={"file": (final_filename, content, "application/octet-stream")},
            )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Teiid unreachable: {exc}") from exc

    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=f"Teiid import failed: {resp.text}")

    teiid_result = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"raw": resp.text}
    if "error" in teiid_result:
        raise HTTPException(status_code=422, detail=teiid_result["error"])

    # Detect column types and create FileSourceMeta
    column_types = detect_column_types(content, final_filename)
    view_name = compute_view_name(final_filename)

    resolved_project_id: int | None = None
    if project_id is not None:
        project = await session.get(Project, project_id)
        if project and project.tenant_id == context.tenant_id:
            resolved_project_id = project_id

    existing_meta = await session.scalar(
        select(FileSourceMeta).where(
            FileSourceMeta.tenant_id == context.tenant_id,
            FileSourceMeta.owner_id == user.id,
            FileSourceMeta.view_name == view_name,
        )
    )
    if existing_meta is None:
        meta = FileSourceMeta(
            tenant_id=context.tenant_id,
            owner_id=user.id,
            project_id=resolved_project_id,
            view_name=view_name,
            file_name=final_filename,
            vdb_type="user",
            source_format=original_format,
            column_types=column_types or None,
        )
        session.add(meta)
    else:
        meta = existing_meta
        meta.file_name = final_filename
        meta.source_format = original_format
        if column_types:
            meta.column_types = column_types
        if resolved_project_id is not None:
            meta.project_id = resolved_project_id
        meta.archived = False
        meta.archived_at = None

    await session.flush()

    # Persist catalog tag/KPI suggestions with real source_id
    catalog_result = upload_data.get("catalog_result", {})
    from app.services.upload_ai_profiler_service import (
        _persist_suggestions,
        _update_file_meta,
    )
    if catalog_result and meta.id and resolved_project_id:
        await _persist_suggestions(
            session, context.tenant_id, resolved_project_id,
            context.user_id, meta.id, catalog_result,
        )
    if catalog_result and meta.id:
        await _update_file_meta(session, meta.id, catalog_result)

    # Auto-accept tags/KPIs based on user selections (requires project)
    if resolved_project_id and (req.accepted_tag_keys or req.rejected_tag_keys):
        from app.models.ai_asset_metadata import (
            AIAssetTag,
            AIAssetTagSuggestion,
        )
        suggestions = (
            await session.scalars(
                select(AIAssetTagSuggestion).where(
                    AIAssetTagSuggestion.source_id == meta.id,
                    AIAssetTagSuggestion.source_type == "file_datasource",
                    AIAssetTagSuggestion.tenant_id == context.tenant_id,
                )
            )
        ).all()
        accepted_keys = set(req.accepted_tag_keys or [])
        rejected_keys = set(req.rejected_tag_keys or [])
        for s in suggestions:
            if s.tag_key in accepted_keys:
                s.status = "accepted"  # type: ignore[assignment]
                session.add(AIAssetTag(
                    tenant_id=context.tenant_id,
                    project_id=resolved_project_id,
                    source_type="file_datasource",
                    source_id=meta.id,
                    tag_key=s.tag_key,
                    display_name=s.display_name,
                    confidence=s.confidence,
                    source="ai_suggested",
                    created_by=context.user_id,
                ))
            elif s.tag_key in rejected_keys:
                s.status = "rejected"  # type: ignore[assignment]

    if resolved_project_id and (req.accepted_kpi_keys or req.rejected_kpi_keys):
        from app.models.ai_asset_metadata import (
            AIAssetKPI,
            AIAssetKPISuggestion,
        )
        kpi_suggestions = (
            await session.scalars(
                select(AIAssetKPISuggestion).where(
                    AIAssetKPISuggestion.source_id == meta.id,
                    AIAssetKPISuggestion.source_type == "file_datasource",
                    AIAssetKPISuggestion.tenant_id == context.tenant_id,
                )
            )
        ).all()
        accepted_kpi_keys = set(req.accepted_kpi_keys or [])
        rejected_kpi_keys = set(req.rejected_kpi_keys or [])
        for ks in kpi_suggestions:
            if ks.kpi_key in accepted_kpi_keys:
                ks.status = "accepted"  # type: ignore[assignment]
                session.add(AIAssetKPI(
                    tenant_id=context.tenant_id,
                    project_id=resolved_project_id,
                    source_type="file_datasource",
                    source_id=meta.id,
                    kpi_key=ks.kpi_key,
                    display_name=ks.display_name,
                    field_mapping=ks.field_mapping,
                    formula=ks.formula,
                    recommended_chart_type=ks.recommended_chart_type,
                    confidence=ks.confidence,
                    source="ai_suggested",
                    created_by=context.user_id,
                ))
            elif ks.kpi_key in rejected_kpi_keys:
                ks.status = "rejected"  # type: ignore[assignment]

    # Apply user overrides to AI result
    if req.user_notes:
        ai_result["user_notes"] = req.user_notes
    if req.user_nuances:
        ai_result["user_nuances"] = req.user_nuances

    # Persist AI metadata
    ai_profile_data = await metadata_svc.create_ai_profile(
        session,
        data_source_id=meta.id,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        project_id=resolved_project_id,
        file_profile=file_profile,
        ai_result=ai_result,
    )

    # Update tags if user modified them
    if req.accepted_tags is not None:
        await metadata_svc.update_tags(
            session,
            data_source_id=meta.id,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            project_id=resolved_project_id,
            tags=req.accepted_tags,
        )

    # Update recommendation decisions
    if req.recommendation_decisions:
        await metadata_svc.update_recommendations(
            session,
            data_source_id=meta.id,
            recommendations=req.recommendation_decisions,
        )

    # Update user notes
    if req.user_notes or req.user_nuances:
        await metadata_svc.update_user_notes(
            session,
            data_source_id=meta.id,
            user_notes=req.user_notes,
            user_nuances=req.user_nuances,
        )

    await session.commit()

    return {
        "data_source_id": meta.id,
        "view_name": view_name,
        "file_name": final_filename,
        "project_id": resolved_project_id,
        "status": "active",
        "message": "Data source created with AI metadata.",
        "ai_profile": ai_profile_data,
    }


@router.get("/{data_source_id}/ai-profile")
async def get_ai_profile(
    data_source_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Get the AI profile for a data source."""
    result = await metadata_svc.get_ai_profile(session, data_source_id=data_source_id)
    if not result:
        raise HTTPException(status_code=404, detail="No AI profile found for this data source")
    return result


class TagsUpdateRequest(BaseModel):
    tags: list[dict[str, Any]]


@router.patch("/{data_source_id}/tags")
async def update_tags(
    data_source_id: int,
    req: TagsUpdateRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> list[dict[str, Any]]:
    """Update tags for a data source."""
    return await metadata_svc.update_tags(
        session,
        data_source_id=data_source_id,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        project_id=None,
        tags=req.tags,
    )


class RecommendationsUpdateRequest(BaseModel):
    recommendations: list[dict[str, Any]]


@router.patch("/{data_source_id}/recommendations")
async def update_recommendations(
    data_source_id: int,
    req: RecommendationsUpdateRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> list[dict[str, Any]]:
    """Update recommendation statuses."""
    return await metadata_svc.update_recommendations(
        session,
        data_source_id=data_source_id,
        recommendations=req.recommendations,
    )


class NotesUpdateRequest(BaseModel):
    user_notes: str | None = None
    user_nuances: str | None = None


@router.patch("/{data_source_id}/notes")
async def update_notes(
    data_source_id: int,
    req: NotesUpdateRequest,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.EDITOR)),
) -> dict[str, Any]:
    """Update user notes/nuances."""
    result = await metadata_svc.update_user_notes(
        session,
        data_source_id=data_source_id,
        user_notes=req.user_notes,
        user_nuances=req.user_nuances,
    )
    if not result:
        raise HTTPException(status_code=404, detail="No AI profile found")
    return result
