
from __future__ import annotations

import hashlib
import logging
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.file_import_job import FileImportJob
from app.services import malware_scan
from app.services.file_sources import sanitize_filename
from app.services.file_validation import (
    FileValidationError,
    validate_content,
)

logger = logging.getLogger(__name__)


class FileImportError(Exception):
    """An import failed. ``code`` is a safe category, ``message`` is safe text."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(slots=True)
class SafeProvenance:
    source_host: str | None = None
    locator_redacted: str | None = None
    network_connection_id: int | None = None
    remote_etag: str | None = None
    remote_last_modified: str | None = None


@dataclass(slots=True)
class StagedFile:
    """The single contract every acquisition method produces."""

    import_job_id: str
    content_path: Path
    original_filename: str
    sanitized_filename: str
    detected_extension: str
    detected_mime_type: str
    content_family: str
    size_bytes: int
    sha256: str
    acquisition_method: str
    safe_provenance: SafeProvenance


# ── Quarantine ───────────────────────────────────────────────────────────


def quarantine_dir(tenant_id: int, user_id: int, job_id: str) -> Path:
    base = Path(get_settings().file_import_quarantine_path)
    return base / str(tenant_id) / str(user_id) / job_id


def _write_quarantine(
    tenant_id: int, user_id: int, job_id: str, filename: str, data: bytes
) -> Path:
    directory = quarantine_dir(tenant_id, user_id, job_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_bytes(data)
    path.chmod(0o600)
    return path


def discard_quarantine(job: FileImportJob) -> None:
    """Remove a job's staged bytes. Safe to call more than once."""
    if not job.storage_key:
        return
    directory = Path(job.storage_key).parent
    shutil.rmtree(directory, ignore_errors=True)
    job.storage_key = None


def read_staged_bytes(job: FileImportJob) -> bytes:
    if not job.storage_key:
        raise FileImportError("STAGED_FILE_MISSING", "The staged file is no longer available.")
    path = Path(job.storage_key)
    if not path.is_file():
        raise FileImportError("STAGED_FILE_MISSING", "The staged file is no longer available.")
    return path.read_bytes()


# ── Acquisition ──────────────────────────────────────────────────────────


def _new_job(
    *,
    tenant_id: int,
    user_id: int,
    project_id: int | None,
    method: str,
) -> FileImportJob:
    settings = get_settings()
    return FileImportJob(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        requested_by=user_id,
        project_id=project_id,
        method=method,
        status="validating",
        expires_at=datetime.now(UTC)
        + timedelta(seconds=settings.file_import_job_ttl_seconds),
    )


async def _stage(
    session: AsyncSession,
    job: FileImportJob,
    *,
    data: bytes,
    original_filename: str,
    declared_mime_type: str | None,
    provenance: SafeProvenance,
    allowed_families: tuple[str, ...],
) -> StagedFile:
    """Validate, scan, fingerprint, and quarantine acquired bytes."""
    settings = get_settings()
    if len(data) > settings.file_import_max_bytes:
        raise FileImportError(
            "FILE_TOO_LARGE",
            f"That file exceeds the {settings.file_import_max_bytes // (1024 * 1024)}"
            "MB limit.",
        )

    sanitized = sanitize_filename(original_filename)
    try:
        validated = validate_content(
            data,
            sanitized,
            declared_mime_type=declared_mime_type,
            allowed_families=allowed_families,
        )
    except FileValidationError as exc:
        raise FileImportError(exc.code, exc.message) from exc

    job.status = "scanning"
    try:
        scan = await malware_scan.scan_bytes(data)
    except malware_scan.MalwareScanError as exc:
        raise FileImportError(exc.code, exc.message) from exc
    if scan.is_blocking:
        logger.warning(
            "malware scan blocked import job=%s tenant=%s signature=%s",
            job.id,
            job.tenant_id,
            scan.signature,
        )
        raise FileImportError(
            "SECURITY_BLOCKED", "That file was blocked by the security scanner."
        )

    digest = hashlib.sha256(data).hexdigest()
    path = _write_quarantine(
        job.tenant_id, job.requested_by, job.id, sanitized, data
    )

    job.original_file_name = original_filename[:512]
    job.sanitized_file_name = sanitized
    job.detected_extension = validated.extension
    job.detected_mime_type = validated.mime_type
    job.content_family = validated.content_family
    job.file_size_bytes = len(data)
    job.sha256 = digest
    job.storage_key = str(path)
    job.source_host = provenance.source_host
    job.source_locator_redacted = provenance.locator_redacted
    job.network_connection_id = provenance.network_connection_id
    job.remote_etag = provenance.remote_etag
    job.remote_last_modified = provenance.remote_last_modified
    job.retrieved_at = datetime.now(UTC)
    job.status = "profiling"
    await session.flush()

    logger.info(
        "file import staged job=%s tenant=%s method=%s family=%s locator=%s",
        job.id,
        job.tenant_id,
        job.method,
        job.content_family,
        job.source_locator_redacted or "local",
    )

    return StagedFile(
        import_job_id=job.id,
        content_path=path,
        original_filename=original_filename,
        sanitized_filename=sanitized,
        detected_extension=validated.extension,
        detected_mime_type=validated.mime_type,
        content_family=validated.content_family,
        size_bytes=len(data),
        sha256=digest,
        acquisition_method=job.method,
        safe_provenance=provenance,
    )
