"""Chat attachment upload, storage, and content extraction for AI Assistant messages."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import ChatAttachment, Tenant
from app.services.document_extraction_service import extract_text
from app.services.s3_storage import S3StorageService
from app.services.upload_intake import UploadRejected, classify_upload

logger = logging.getLogger(__name__)

CHAT_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp"})
CHAT_DOCUMENT_EXTENSIONS = frozenset({".pdf", ".docx", ".pptx", ".txt", ".md"})
CHAT_TEXT_EXTENSIONS = frozenset({".csv", ".json", ".xml", ".txt", ".md"})
CHAT_SPREADSHEET_EXTENSIONS = frozenset({".xlsx", ".xls"})


class ChatAttachmentRejected(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _safe_filename(name: str) -> str:
    base = Path(name).name
    base = re.sub(r"[^\w.\-]", "_", base)
    base = re.sub(r"_{2,}", "_", base)
    base = base.strip("._")
    if not base or base == ".":
        base = "attachment"
    return base[:200] or "attachment"


def _image_mime(extension: str) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(extension, "application/octet-stream")


def _is_image_content(content: bytes, extension: str) -> bool:
    if extension in (".png",) and content.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if extension in (".jpg", ".jpeg") and content.startswith(b"\xff\xd8"):
        return True
    if extension == ".webp" and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return True
    return False


def _extract_text_content(content: bytes, extension: str) -> dict[str, Any] | None:
    if extension == ".csv":
        try:
            text = content.decode("utf-8", errors="replace")
            lines = text.splitlines()
            preview_lines = lines[:101]
            return {
                "document_text": "\n".join(preview_lines),
                "truncated": len(lines) > 101,
                "line_count": len(lines),
                "type": "csv_preview",
            }
        except Exception as exc:
            logger.warning("CSV preview failed: %s", exc)
            return None
    if extension in (".json", ".xml", ".txt", ".md"):
        try:
            text = content.decode("utf-8", errors="replace")
            return {
                "document_text": text[:200_000],
                "truncated": len(text) > 200_000,
                "type": "text",
            }
        except Exception as exc:
            logger.warning("Text preview failed: %s", exc)
            return None
    return None


class ChatAttachmentService:
    def __init__(self) -> None:
        self._settings = get_settings()

    async def upload(
        self,
        session: AsyncSession,
        tenant: Tenant,
        user_id: int,
        conversation_id: int,
        project_id: int | None,
        file: UploadFile,
    ) -> ChatAttachment:
        settings = self._settings
        if not settings.chat_attachments_v1_enabled or not tenant.chat_attachments_enabled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Chat attachments are not enabled for this tenant.",
            )

        from app.services.tenant_storage_resolver import TenantStorageResolver

        binding = await TenantStorageResolver(session).resolve_for_org(tenant.id)
        s3 = S3StorageService(binding) if settings.s3_enabled or binding.dedicated else None

        filename = file.filename or "attachment"
        safe_name = _safe_filename(filename)
        content = await file.read()
        if len(content) > settings.chat_attachment_max_bytes:
            raise ChatAttachmentRejected(
                "too_large",
                f"{filename} exceeds {settings.chat_attachment_max_bytes // (1024 * 1024)}MB limit.",
            )

        ext = Path(safe_name).suffix.lower()
        if ext not in {e.strip() for e in settings.chat_attachment_allowed_extensions.split(",")}:
            raise ChatAttachmentRejected("unsupported_type", f"{filename}: unsupported file type.")

        if ext in CHAT_IMAGE_EXTENSIONS:
            if not _is_image_content(content, ext):
                raise ChatAttachmentRejected("signature_mismatch", "Image file contents do not match extension.")
            mime = _image_mime(ext)
            extraction: dict[str, Any] | None = {"type": "image", "mime_type": mime}
        else:
            try:
                classification = classify_upload(
                    filename,
                    content,
                    declared_mime=file.content_type,
                    max_bytes=settings.chat_attachment_max_bytes,
                )
                mime = classification.detected_mime or file.content_type or "application/octet-stream"
            except UploadRejected as exc:
                raise ChatAttachmentRejected(exc.code, exc.message) from exc

            if ext in CHAT_SPREADSHEET_EXTENSIONS:
                extraction = {"type": "spreadsheet", "mime_type": mime}
            elif ext in CHAT_DOCUMENT_EXTENSIONS:
                extraction = None  # extracted from disk later
            else:
                extraction = _extract_text_content(content, ext)

        sha256 = hashlib.sha256(content).hexdigest()

        # De-duplicate: reuse an existing identical attachment in the same conversation.
        existing = await session.scalar(
            select(ChatAttachment).where(
                ChatAttachment.tenant_id == tenant.id,
                ChatAttachment.conversation_id == conversation_id,
                ChatAttachment.sha256 == sha256,
                ChatAttachment.deleted_at.is_(None),
            )
        )
        if existing:
            return existing

        attachment = ChatAttachment(
            tenant_id=tenant.id,
            project_id=project_id,
            conversation_id=conversation_id,
            uploaded_by=user_id,
            original_filename=filename,
            safe_filename=safe_name,
            mime_type=mime,
            byte_size=len(content),
            sha256=sha256,
            storage_key="",
            status="uploaded",
        )
        session.add(attachment)
        await session.flush()

        storage_key = f"customers/{tenant.id}/chat-attachments/{attachment.id}/{safe_name}"
        local_path = binding.local_base / storage_key
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(content)

        if s3 is not None:
            try:
                s3.upload_file(str(local_path), storage_key)
            except Exception as exc:
                logger.exception("S3 upload failed for chat attachment %s: %s", attachment.id, exc)
                raise ChatAttachmentRejected("storage_failed", "Could not persist attachment to durable storage.") from exc

        attachment.storage_key = storage_key

        if extraction is None and ext in CHAT_DOCUMENT_EXTENSIONS:
            try:
                extraction = extract_text(str(local_path), ext)
            except Exception as exc:
                logger.warning("Document extraction failed for %s: %s", attachment.id, exc)
                extraction = {"type": "document", "extraction_error": str(exc)}

        if extraction is not None:
            attachment.extraction_result = extraction

        attachment.status = "ready"
        await session.flush()
        return attachment

    async def get(
        self,
        session: AsyncSession,
        tenant_id: int,
        attachment_id: int,
    ) -> ChatAttachment | None:
        return await session.scalar(
            select(ChatAttachment).where(
                ChatAttachment.id == attachment_id,
                ChatAttachment.tenant_id == tenant_id,
                ChatAttachment.deleted_at.is_(None),
            )
        )

    async def delete(
        self,
        session: AsyncSession,
        tenant_id: int,
        user_id: int,
        attachment_id: int,
    ) -> bool:
        attachment = await self.get(session, tenant_id, attachment_id)
        if attachment is None:
            return False
        if attachment.uploaded_by != user_id and attachment.message_id is not None:
            # Only the uploader can delete an unattached file.
            return False
        if attachment.deleted_at is not None:
            return True
        attachment.deleted_at = datetime.now(UTC)
        attachment.status = "deleted"
        await session.flush()
        from app.services.tenant_storage_resolver import TenantStorageResolver

        binding = await TenantStorageResolver(session).resolve_for_org(tenant_id)
        s3 = S3StorageService(binding) if self._settings.s3_enabled or binding.dedicated else None
        if s3 is not None:
            try:
                s3.delete_file(attachment.storage_key)
            except Exception:
                logger.exception("Failed to delete chat attachment %s from S3", attachment.id)
                if binding.dedicated:
                    raise
        local_path = binding.local_base / attachment.storage_key
        try:
            if local_path.exists():
                local_path.unlink()
        except Exception:
            logger.exception("Failed to delete chat attachment %s locally", attachment.id)
        return True


def get_chat_attachment_service() -> ChatAttachmentService:
    return ChatAttachmentService()
