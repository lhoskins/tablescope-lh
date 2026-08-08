
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.file_import_job import FileImportJob
from app.services.ai_file_analysis_service import analyze_file_with_ai
from app.services.file_profile_service import profile_uploaded_file
from app.services.upload_ai_profiler_service import (
    profile_uploaded_file as catalog_profile_file,
)

from .staging import FileImportError, StagedFile, read_staged_bytes

# ── Profiling ────────────────────────────────────────────────────────────


async def profile_staged_file(
    session: AsyncSession,
    job: FileImportJob,
    staged: StagedFile,
    *,
    tenant_id: int,
    user_id: int,
    project_id: int | None,
    source_name: str | None = None,
) -> dict[str, Any]:
    """Profile a staged tabular file and run the existing AI/catalog analysis.

    Returns the same preview payload the builder already consumes, with
    ``import_job_id`` added alongside the legacy ``upload_session_id``.
    """
    data = read_staged_bytes(job)
    file_name = staged.sanitized_filename
    try:
        file_profile = profile_uploaded_file(data, file_name, staged.detected_extension)
    except Exception as exc:
        raise FileImportError("PARSE_FAILED", f"Could not parse file: {exc}") from exc
    if file_profile["column_count"] == 0:
        raise FileImportError("NO_COLUMNS", "No columns detected in file")

    ai_result = await analyze_file_with_ai(
        file_profile,
        tenant_id=tenant_id,
        user_id=user_id,
        project_id=project_id or 0,
    )

    columns_for_catalog = [
        {"name": f["field_name"], "type": f.get("detected_type", "string")}
        for f in file_profile.get("fields", [])
    ]
    catalog_result = await catalog_profile_file(
        session=session,
        tenant_id=tenant_id,
        user_id=user_id,
        project_id=project_id or 0,
        source_id=0,
        view_name=file_name.rsplit(".", 1)[0] if "." in file_name else file_name,
        file_name=file_name,
        columns=columns_for_catalog,
        sample_rows=file_profile.get("sample_rows", []),
        persist=False,
    )

    job.profile_json = {
        "file_profile": file_profile,
        "ai_result": ai_result,
        "catalog_result": catalog_result,
        "source_name": source_name,
    }
    job.status = "ready"
    await session.flush()

    return build_preview_payload(job, file_profile, ai_result, catalog_result)


def build_preview_payload(
    job: FileImportJob,
    file_profile: dict[str, Any],
    ai_result: dict[str, Any],
    catalog_result: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the builder's preview response for a profiled import job."""
    return {
        "import_job_id": job.id,
        # Legacy alias kept until every caller migrates to import_job_id.
        "upload_session_id": job.id,
        "acquisition_method": job.method,
        "content_family": job.content_family,
        "source_host": job.source_host,
        "source_locator_redacted": job.source_locator_redacted,
        "sha256": job.sha256,
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
                    (
                        af["description"]
                        for af in ai_result.get("fields", [])
                        if af["field_name"] == pf["field_name"]
                    ),
                    "",
                ),
                "ai_quality_notes": next(
                    (
                        af["quality_notes"]
                        for af in ai_result.get("fields", [])
                        if af["field_name"] == pf["field_name"]
                    ),
                    "",
                ),
            }
            for pf in file_profile["fields"]
        ],
        "tags": [
            {**t, "source": "catalog", "accepted": True}
            for t in catalog_result.get("suggested_tags", [])
        ]
        or [
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
