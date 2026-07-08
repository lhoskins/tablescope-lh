"""User avatar storage.

Avatars are validated images stored under the tenant/user customer directory
(``{customer_base_path}/{tenant_id}/{user_id}/avatar/``) and, best-effort, synced
to S3. The image is served back through an authenticated-free, opaque URL
(``/api/users/{user_id}/avatar``) — the raw filesystem path is never exposed.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)

MAX_AVATAR_BYTES = 5 * 1024 * 1024  # 5 MB

# Allowed image types (no SVG). Maps content-type -> canonical extension.
ALLOWED_CONTENT_TYPES: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
}
ALLOWED_EXTENSIONS: dict[str, str] = {
    "png": "png",
    "jpg": "jpg",
    "jpeg": "jpg",
    "webp": "webp",
}

# Minimal magic-byte signatures so we don't trust the declared content-type alone.
_MAGIC = {
    "png": [b"\x89PNG\r\n\x1a\n"],
    "jpg": [b"\xff\xd8\xff"],
    "webp": [b"RIFF"],  # RIFF....WEBP
}


class AvatarValidationError(Exception):
    """Raised when an uploaded avatar fails validation."""


def _resolve_extension(content_type: str | None, filename: str | None) -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in ALLOWED_CONTENT_TYPES:
        return ALLOWED_CONTENT_TYPES[ct]
    ext = ""
    if filename and "." in filename:
        ext = filename.rsplit(".", 1)[-1].lower()
    if ext in ALLOWED_EXTENSIONS:
        return ALLOWED_EXTENSIONS[ext]
    raise AvatarValidationError(
        "Unsupported image type. Use PNG, JPG, or WEBP."
    )


def _check_magic(ext: str, content: bytes) -> None:
    sigs = _MAGIC.get(ext, [])
    if sigs and not any(content.startswith(sig) for sig in sigs):
        # WEBP: RIFF container with 'WEBP' at offset 8.
        if ext == "webp" and content[8:12] == b"WEBP":
            return
        raise AvatarValidationError("File content does not match an image type.")


def validate_avatar(
    *, content: bytes, content_type: str | None, filename: str | None
) -> str:
    """Validate the avatar bytes and return the canonical extension.

    Raises :class:`AvatarValidationError` on invalid type/size/content.
    """
    if not content:
        raise AvatarValidationError("Empty file.")
    if len(content) > MAX_AVATAR_BYTES:
        raise AvatarValidationError("Image too large (max 5 MB).")
    ext = _resolve_extension(content_type, filename)
    _check_magic(ext, content)
    return ext


def _avatar_dir(tenant_id: int, user_id: int) -> Path:
    base = get_settings().customer_base_path
    return Path(base) / str(tenant_id) / str(user_id) / "avatar"


def store_avatar(
    *, tenant_id: int, user_id: int, content: bytes, ext: str
) -> str:
    """Persist the avatar locally (and best-effort to S3); return its file id."""
    avatar_dir = _avatar_dir(tenant_id, user_id)
    avatar_dir.mkdir(parents=True, exist_ok=True)

    file_id = f"{uuid.uuid4().hex}.{ext}"
    dest = avatar_dir / file_id

    # Remove any previous avatar files so we don't accumulate orphans.
    for old in avatar_dir.iterdir():
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
            key = f"{tenant_id}/{user_id}/avatar/{file_id}"
            s3.upload_file(str(dest), key)
        except Exception as exc:  # non-fatal
            logger.warning("Avatar S3 sync failed (non-fatal): %s", exc)

    return file_id


def read_avatar(
    *, tenant_id: int, user_id: int, file_id: str
) -> tuple[bytes, str] | None:
    """Return (bytes, content_type) for the stored avatar, or None if missing."""
    # Guard against path traversal — file_id must be a bare filename.
    if not file_id or "/" in file_id or "\\" in file_id or ".." in file_id:
        return None
    path = _avatar_dir(tenant_id, user_id) / file_id
    if not path.is_file():
        # Fall back to S3 if the local copy is gone (e.g. fresh container).
        settings = get_settings()
        if settings.s3_enabled:
            try:
                from app.services.s3_storage import S3StorageService

                S3StorageService().download_file(
                    f"{tenant_id}/{user_id}/avatar/{file_id}", str(path)
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
