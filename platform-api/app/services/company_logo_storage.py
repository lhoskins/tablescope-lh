"""Tenant company-logo storage.

Company logos are validated images stored under the tenant's customer directory
(``{customer_base_path}/{tenant_id}/logo/``) and, best-effort, synced to S3. The
image is served back through an opaque URL (``/api/tenants/{tenant_id}/logo``) —
the raw filesystem path is never exposed.

Image validation (type/size/magic-bytes) is reused from :mod:`avatar_storage`;
PNG, JPG/JPEG and WEBP are accepted (no SVG).
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from app.config import get_settings
from app.services.avatar_storage import (
    AvatarValidationError as CompanyLogoValidationError,
)
from app.services.avatar_storage import (
    validate_avatar as validate_company_logo,
)

logger = logging.getLogger(__name__)

__all__ = [
    "CompanyLogoValidationError",
    "read_company_logo",
    "store_company_logo",
    "validate_company_logo",
]


def _logo_dir(tenant_id: int) -> Path:
    base = get_settings().customer_base_path
    return Path(base) / str(tenant_id) / "logo"


def store_company_logo(*, tenant_id: int, content: bytes, ext: str) -> str:
    """Persist the company logo locally (and best-effort to S3); return file id."""
    logo_dir = _logo_dir(tenant_id)
    logo_dir.mkdir(parents=True, exist_ok=True)

    file_id = f"{uuid.uuid4().hex}.{ext}"
    dest = logo_dir / file_id

    # Remove any previous logo files so we don't accumulate orphans.
    for old in logo_dir.iterdir():
        if old.is_file():
            try:
                old.unlink()
            except OSError:
                pass

    dest.write_bytes(content)

    settings = get_settings()
    if settings.s3_enabled:
        try:
            from app.services.s3_storage import S3StorageService

            s3 = S3StorageService()
            key = f"{tenant_id}/logo/{file_id}"
            s3.upload_file(str(dest), key)
        except Exception as exc:  # non-fatal
            logger.warning("Company logo S3 sync failed (non-fatal): %s", exc)

    return file_id


def read_company_logo(
    *, tenant_id: int, file_id: str
) -> tuple[bytes, str] | None:
    """Return (bytes, content_type) for the stored logo, or None if missing."""
    # Guard against path traversal — file_id must be a bare filename.
    if not file_id or "/" in file_id or "\\" in file_id or ".." in file_id:
        return None
    path = _logo_dir(tenant_id) / file_id
    if not path.is_file():
        # Fall back to S3 if the local copy is gone (e.g. fresh container).
        settings = get_settings()
        if settings.s3_enabled:
            try:
                from app.services.s3_storage import S3StorageService

                S3StorageService().download_file(
                    f"{tenant_id}/logo/{file_id}", str(path)
                )
            except Exception:  # missing remote is just a 404
                return None
        if not path.is_file():
            return None
    ext = file_id.rsplit(".", 1)[-1].lower() if "." in file_id else ""
    content_type = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
    }.get(ext, "application/octet-stream")
    return path.read_bytes(), content_type
