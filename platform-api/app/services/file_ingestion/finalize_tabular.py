
from __future__ import annotations

import asyncio
import glob
import os
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.file_import_job import FileImportJob
from app.models.file_source_meta import FileSourceMeta
from app.services.vdb_management import VDBManagementService, VDBProvisioningError

from .jobs import apply_provenance
from .remote_vdb import add_remote_csv_view
from .staging import FileImportError, discard_quarantine, logger, read_staged_bytes


@dataclass(slots=True)
class FinalizeOptions:
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


async def _ensure_user_vdb(
    session: AsyncSession,
    *,
    tenant_id: int,
    user_id: int,
    endpoint: Any,
) -> Any:
    """Return the user's VDB registry row, creating it against the tenant Teiid if missing.

    The VDB file can already exist on disk (e.g. a previous upload auto-provisioned
    it) or be created on demand. Either way, a matching ``UserVDB`` row is inserted
    so the rest of the platform can route queries to it.
    """
    from app.models.user_vdb import UserVDB
    from app.services.vdb_management import VDBManagementService, VDBProvisioningError

    existing = await session.scalar(
        select(UserVDB).where(
            UserVDB.tenant_id == tenant_id, UserVDB.user_id == user_id
        )
    )
    if existing is not None:
        return existing

    vdb_path = os.path.join(
        endpoint.vdb_host_path or get_settings().customer_base_path,
        str(tenant_id),
        str(user_id),
        "vdb",
    )

    def _pick_vdb_id() -> str | None:
        if not os.path.isdir(vdb_path):
            return None
        files = glob.glob(os.path.join(vdb_path, "*-vdb.xml"))
        if not files:
            return None
        if len(files) == 1:
            return os.path.basename(files[0]).replace("-vdb.xml", "")
        newest = max(files, key=os.path.getmtime)
        return os.path.basename(newest).replace("-vdb.xml", "")

    vdb_id = await asyncio.to_thread(_pick_vdb_id)

    if vdb_id is None:
        vdb_svc = await VDBManagementService.for_org(session, tenant_id)
        try:
            result = await vdb_svc.create_user_vdb(
                org_id=tenant_id, user_id=user_id
            )
            vdb_id = result.vdb_id
        except VDBProvisioningError as exc:
            raise FileImportError(
                "VDB_PROVISIONING_FAILED",
                "Failed to auto-provision user VDB. Please contact administrator.",
            ) from exc
        finally:
            await vdb_svc.aclose()

    user_vdb = UserVDB(
        tenant_id=tenant_id,
        user_id=user_id,
        vdb_id=vdb_id,
        vdb_username="test",
        encrypted_password="test",
        vdb_host=getattr(endpoint, "pg_host", get_settings().teiid_pg_host),
        vdb_port=getattr(endpoint, "pg_port", get_settings().teiid_pg_port),
        is_active=True,
        health_status="deployed",
    )
    session.add(user_vdb)
    await session.flush()
    return user_vdb


async def _deploy_remote_view(
    session: AsyncSession,
    endpoint: Any,
    user_vdb: Any,
    *,
    data_source_id: int,
    tenant_id: int,
    user_id: int,
    view_name: str,
    column_types: list[dict[str, Any]] | None,
    original_format: str | None,
) -> dict[str, Any]:
    """Edit the tenant VDB to add a live remote-file view and redeploy it."""
    from app.services.file_sources.sanitize import sanitize_column_name

    if not column_types:
        raise FileImportError("UNPROFILED", "Could not determine columns for live source")

    for col in column_types:
        col["field"] = sanitize_column_name(col.get("name") or "col")

    headers = [c["name"] for c in column_types if isinstance(c, dict) and c.get("name")]
    delimiter = "\t" if (original_format or "").lower() in {"tsv", "txt"} else ","

    vdb_id = user_vdb.vdb_id
    host_base_path = getattr(endpoint, "vdb_host_path", None) or get_settings().customer_base_path
    container_base_path = getattr(
        endpoint, "vdb_container_path", None
    ) or host_base_path
    host_vdb_file_path = os.path.join(
        host_base_path, str(tenant_id), str(user_id), "vdb", f"{vdb_id}-vdb.xml"
    )
    container_vdb_file_path = os.path.join(
        container_base_path, str(tenant_id), str(user_id), "vdb", f"{vdb_id}-vdb.xml"
    )

    def _edit_and_write() -> None:
        if not os.path.isfile(host_vdb_file_path):
            raise FileImportError("VDB_NOT_FOUND", f"Tenant VDB file not found: {host_vdb_file_path}")
        with open(host_vdb_file_path, encoding="utf-8") as fh:
            xml = fh.read()
        xml = add_remote_csv_view(xml, view_name, headers, data_source_id, delimiter)
        with open(host_vdb_file_path, "w", encoding="utf-8") as fh:
            fh.write(xml)
        try:
            # The VDB directory is setgid wildfly; new files inherit the group.
            # Make the file group-writable so the WildFly/Teiid servlet can also
            # update it (e.g. when registering new database sources).
            os.chmod(host_vdb_file_path, 0o664)
        except OSError:
            pass

    await asyncio.to_thread(_edit_and_write)

    vdb_svc = await VDBManagementService.for_org(session, tenant_id)
    try:
        # Pass the path as the Teiid servlet sees it. For dedicated tenant
        # containers the VDB volume is mounted at a different host path than
        # the platform-api writes to, so the container-internal path is required.
        await vdb_svc.redeploy_vdb(str(vdb_id), vdb_file_path=container_vdb_file_path)
    except VDBProvisioningError as exc:
        raise FileImportError("TEIID_IMPORT_FAILED", str(exc)) from exc
    finally:
        await vdb_svc.aclose()

    return {"redeployed": True, "vdb_id": vdb_id, "data_source_id": data_source_id}


async def finalize_tabular_import(
    session: AsyncSession,
    job: FileImportJob,
    options: FinalizeOptions,
    *,
    tenant_id: int,
    user_id: int,
) -> dict[str, Any]:
    """Register a staged tabular file as a data source.

    Sanitizes/converts the file, imports it into the tenant's Teiid VDB,
    persists ``FileSourceMeta`` with acquisition provenance, applies the AI /
    catalog metadata, and creates the auto saved query — the same sequence
    local uploads have always followed. Re-finalizing a completed job returns
    the stored result instead of creating a second view.
    """
    import httpx

    from app.models.project import Project
    from app.models.tenant import Tenant
    from app.models.user import User
    from app.services.file_sources import (
        compute_view_name,
        detect_column_types,
        display_source,
        prepare_upload_content,
    )
    from app.services.tenant_teiid_resolver import TenantTeiidResolver

    if job.status == "completed" and job.result_json:
        return job.result_json
    if job.status in ("cancelled", "expired"):
        raise FileImportError(
            "JOB_NOT_AVAILABLE", "That import was cancelled and cannot be finalized."
        )
    if job.content_family != "tabular":
        raise FileImportError(
            "WRONG_CONTENT_FAMILY",
            "That file is a document; assign it to a project instead.",
        )

    profile = job.profile_json or {}
    file_profile = profile.get("file_profile")
    ai_result = dict(profile.get("ai_result") or {})
    catalog_result = profile.get("catalog_result") or {}
    if not file_profile:
        raise FileImportError("NOT_PROFILED", "That import has not been profiled yet.")

    job.status = "finalizing"
    content = read_staged_bytes(job)
    file_name = job.sanitized_file_name or "upload.csv"
    project_id = options.project_id or job.project_id

    user = await session.get(User, user_id)
    if user is None:
        raise FileImportError("USER_NOT_FOUND", "User not found")
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise FileImportError("TENANT_NOT_FOUND", "Tenant not found")

    original_format = job.detected_extension
    final_filename, content, _ = prepare_upload_content(file_name, content)
    display_name, _ = display_source(final_filename, original_format)

    column_types = detect_column_types(content, final_filename)
    view_name = compute_view_name(final_filename)

    endpoint = await TenantTeiidResolver(session).resolve_for_org(tenant_id)
    user_vdb = await _ensure_user_vdb(
        session, tenant_id=tenant_id, user_id=user.id, endpoint=endpoint
    )

    resolved_project_id: int | None = None
    if project_id is not None:
        project = await session.get(Project, project_id)
        if project and project.tenant_id == tenant_id:
            resolved_project_id = project_id

    existing_meta = await session.scalar(
        select(FileSourceMeta).where(
            FileSourceMeta.tenant_id == tenant_id,
            FileSourceMeta.owner_id == user.id,
            FileSourceMeta.view_name == view_name,
        )
    )
    if existing_meta is None:
        meta = FileSourceMeta(
            tenant_id=tenant_id,
            owner_id=user.id,
            project_id=resolved_project_id,
            view_name=view_name,
            file_name=display_name,
            vdb_type="user",
            source_format=original_format,
            column_types=column_types or None,
        )
        session.add(meta)
    else:
        meta = existing_meta
        meta.file_name = display_name
        meta.source_format = original_format
        if column_types:
            meta.column_types = column_types
        if resolved_project_id is not None:
            meta.project_id = resolved_project_id
        meta.archived = False
        meta.archived_at = None
    await session.flush()

    if job.live_source_params is not None:
        teiid_result = await _deploy_remote_view(
            session,
            endpoint,
            user_vdb,
            data_source_id=meta.id,
            tenant_id=tenant_id,
            user_id=user.id,
            view_name=view_name,
            column_types=column_types,
            original_format=original_format,
        )
    else:
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
                    files={
                        "file": (final_filename, content, "application/octet-stream")
                    },
                )
        except httpx.RequestError as exc:
            raise FileImportError("TEIID_UNREACHABLE", f"Teiid unreachable: {exc}") from exc

        if resp.status_code >= 400:
            raise FileImportError(
                "TEIID_IMPORT_FAILED", f"Teiid import failed: {resp.text}"
            )
        teiid_result = (
            resp.json()
            if resp.headers.get("content-type", "").startswith("application/json")
            else {"raw": resp.text}
        )
        if "error" in teiid_result:
            raise FileImportError("TEIID_IMPORT_FAILED", str(teiid_result["error"]))

        from app.services.s3_storage import S3StorageService
        from app.services.tenant_storage_resolver import TenantStorageResolver

        binding = await TenantStorageResolver(session).resolve_for_org(tenant_id)
        if get_settings().s3_enabled or binding.dedicated:
            storage = S3StorageService(binding)
            local_upload = binding.local_base / str(tenant_id) / str(user.id) / "uploads" / final_filename
            storage.upload_file(
                str(local_upload),
                storage.get_s3_key_for_upload(tenant_id, user.id, final_filename),
            )
            vdb_dir = binding.local_base / str(tenant_id) / str(user.id) / "vdb"
            synced = storage.sync_local_to_s3(
                str(vdb_dir), f"customers/{tenant_id}/{user.id}/vdb"
            )
            if binding.dedicated and synced == 0:
                raise FileImportError(
                    "PRIVATE_STORAGE_FAILED",
                    "Teiid did not produce a VDB XML file for private storage.",
                )

    apply_provenance(meta, job)
    await session.flush()

    ai_profile_data = await _persist_ai_metadata(
        session,
        meta=meta,
        options=options,
        tenant_id=tenant_id,
        user_id=user_id,
        resolved_project_id=resolved_project_id,
        file_profile=file_profile,
        ai_result=ai_result,
        catalog_result=catalog_result,
    )

    if resolved_project_id is not None:
        try:
            from app.services.auto_query import ensure_datasource_query

            col_names = [
                c.get("field") or c["name"]
                for c in (column_types or [])
                if isinstance(c, dict) and c.get("name")
            ]
            await ensure_datasource_query(
                session,
                project_id=resolved_project_id,
                owner_id=user.id,
                display_name=final_filename,
                view_name=view_name,
                columns=col_names,
            )
        except Exception as exc:  # non-fatal
            logger.warning(
                "Auto-create query for %s failed (non-fatal): %s", view_name, exc
            )

    result = {
        "data_source_id": meta.id,
        "import_job_id": job.id,
        "view_name": view_name,
        "file_name": display_name,
        "project_id": resolved_project_id,
        "acquisition_method": job.method,
        "source_locator_redacted": job.source_locator_redacted,
        "status": "active",
        "message": "Data source created with AI metadata.",
        "ai_profile": ai_profile_data,
    }
    job.status = "completed"
    job.finalized_data_source_id = meta.id
    job.result_json = result
    discard_quarantine(job)
    logger.info(
        "file import finalized job=%s tenant=%s method=%s view=%s",
        job.id,
        tenant_id,
        job.method,
        view_name,
    )
    return result


async def _persist_ai_metadata(
    session: AsyncSession,
    *,
    meta: FileSourceMeta,
    options: FinalizeOptions,
    tenant_id: int,
    user_id: int,
    resolved_project_id: int | None,
    file_profile: dict[str, Any],
    ai_result: dict[str, Any],
    catalog_result: dict[str, Any],
) -> dict[str, Any]:
    """Apply catalog suggestions, tag/KPI decisions, and notes to a source."""
    from app.models.ai_asset_metadata import (
        AIAssetKPI,
        AIAssetKPISuggestion,
        AIAssetTag,
        AIAssetTagSuggestion,
    )
    from app.services import data_source_metadata_service as metadata_svc
    from app.services.upload_ai_profiler_service import (
        _persist_suggestions,
        _update_file_meta,
    )

    if catalog_result and meta.id and resolved_project_id:
        await _persist_suggestions(
            session, tenant_id, resolved_project_id, user_id, meta.id, catalog_result
        )
    if catalog_result and meta.id:
        await _update_file_meta(session, meta.id, catalog_result)

    if resolved_project_id and (options.accepted_tag_keys or options.rejected_tag_keys):
        suggestions = (
            await session.scalars(
                select(AIAssetTagSuggestion).where(
                    AIAssetTagSuggestion.source_id == meta.id,
                    AIAssetTagSuggestion.source_type == "file_datasource",
                    AIAssetTagSuggestion.tenant_id == tenant_id,
                )
            )
        ).all()
        accepted_keys = set(options.accepted_tag_keys or [])
        rejected_keys = set(options.rejected_tag_keys or [])
        for s in suggestions:
            if s.tag_key in accepted_keys:
                s.status = "accepted"  # type: ignore[assignment]
                session.add(
                    AIAssetTag(
                        tenant_id=tenant_id,
                        project_id=resolved_project_id,
                        source_type="file_datasource",
                        source_id=meta.id,
                        tag_key=s.tag_key,
                        display_name=s.display_name,
                        confidence=s.confidence,
                        source="ai_suggested",
                        created_by=user_id,
                    )
                )
            elif s.tag_key in rejected_keys:
                s.status = "rejected"  # type: ignore[assignment]

    if resolved_project_id and (options.accepted_kpi_keys or options.rejected_kpi_keys):
        kpi_suggestions = (
            await session.scalars(
                select(AIAssetKPISuggestion).where(
                    AIAssetKPISuggestion.source_id == meta.id,
                    AIAssetKPISuggestion.source_type == "file_datasource",
                    AIAssetKPISuggestion.tenant_id == tenant_id,
                )
            )
        ).all()
        accepted_kpi_keys = set(options.accepted_kpi_keys or [])
        rejected_kpi_keys = set(options.rejected_kpi_keys or [])
        for ks in kpi_suggestions:
            if ks.kpi_key in accepted_kpi_keys:
                ks.status = "accepted"  # type: ignore[assignment]
                session.add(
                    AIAssetKPI(
                        tenant_id=tenant_id,
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
                        created_by=user_id,
                    )
                )
            elif ks.kpi_key in rejected_kpi_keys:
                ks.status = "rejected"  # type: ignore[assignment]

    if options.user_notes:
        ai_result["user_notes"] = options.user_notes
    if options.user_nuances:
        ai_result["user_nuances"] = options.user_nuances

    ai_profile_data = await metadata_svc.create_ai_profile(
        session,
        data_source_id=meta.id,
        tenant_id=tenant_id,
        user_id=user_id,
        project_id=resolved_project_id,
        file_profile=file_profile,
        ai_result=ai_result,
    )

    if options.accepted_tags is not None:
        await metadata_svc.update_tags(
            session,
            data_source_id=meta.id,
            tenant_id=tenant_id,
            user_id=user_id,
            project_id=resolved_project_id,
            tags=options.accepted_tags,
        )
    if options.recommendation_decisions:
        await metadata_svc.update_recommendations(
            session,
            data_source_id=meta.id,
            recommendations=options.recommendation_decisions,
        )
    if options.user_notes or options.user_nuances:
        await metadata_svc.update_user_notes(
            session,
            data_source_id=meta.id,
            user_notes=options.user_notes,
            user_nuances=options.user_nuances,
        )
    return ai_profile_data
