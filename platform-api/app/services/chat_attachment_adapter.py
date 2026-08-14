"""Build attachment context blocks for the conversational analytics pipeline.

The adapter is invoked only when ``attachment_ids`` are present and the tenant
has chat attachments enabled. It resolves authorized attachment rows,
truncates extracted content to fit the model context, and returns a plain-text
block that can be prepended to the user question without changing SQL
generation or grounding behavior.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import ChatAttachment

logger = logging.getLogger(__name__)

MAX_ATTACHMENT_CHARS = 50_000
MAX_ATTACHMENTS_PER_TURN = 10


def _format_attachment(attachment: ChatAttachment) -> str:
    lines = [
        f"--- Attachment: {attachment.original_filename} ---",
        f"Type: {attachment.mime_type}",
        f"Size: {attachment.byte_size} bytes",
    ]
    extraction = attachment.extraction_result or {}
    text = extraction.get("document_text") or extraction.get("text") or ""
    if text:
        if len(text) > MAX_ATTACHMENT_CHARS:
            text = text[:MAX_ATTACHMENT_CHARS].rstrip() + "\n[attachment truncated]"
        lines.append(text)
    else:
        lines.append("[No extractable text content; file is available for model reference.]")
    lines.append("")
    return "\n".join(lines)


async def build_attachment_context(
    session: AsyncSession,
    tenant_id: int,
    attachment_ids: list[int],
) -> str | None:
    settings = get_settings()
    if not settings.chat_attachments_v1_enabled:
        return None
    if not attachment_ids:
        return None
    if len(attachment_ids) > MAX_ATTACHMENTS_PER_TURN:
        attachment_ids = attachment_ids[:MAX_ATTACHMENTS_PER_TURN]

    result = await session.execute(
        select(ChatAttachment).where(
            ChatAttachment.id.in_(attachment_ids),
            ChatAttachment.tenant_id == tenant_id,
            ChatAttachment.deleted_at.is_(None),
        )
    )
    attachments = list(result.scalars().all())
    if len(attachments) != len(attachment_ids):
        logger.warning("Some attachment IDs were missing or not authorized")

    if not attachments:
        return None

    parts = ["The user has provided the following attachments. Use them as context for the question below.\n"]
    for attachment in attachments:
        parts.append(_format_attachment(attachment))
    return "\n".join(parts)
