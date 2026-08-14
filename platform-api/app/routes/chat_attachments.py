"""Chat attachment upload and lifecycle endpoints for the AI Assistant."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import RequestContext
from app.auth.rbac import Role, require_role
from app.database import get_db
from app.models import AnalyticsConversation, ChatAttachment, Tenant
from app.services.chat_attachment_service import (
    ChatAttachmentRejected,
    get_chat_attachment_service,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat/attachments", tags=["Chat Attachments"])


class ChatAttachmentResponse(BaseModel):
    id: int
    conversation_id: int
    message_id: int | None
    original_filename: str
    safe_filename: str
    mime_type: str
    byte_size: int
    sha256: str
    status: str
    status_message: str | None
    extraction_result: dict | None


def _attachment_response(attachment: ChatAttachment) -> ChatAttachmentResponse:
    return ChatAttachmentResponse(
        id=attachment.id,
        conversation_id=attachment.conversation_id,
        message_id=attachment.message_id,
        original_filename=attachment.original_filename,
        safe_filename=attachment.safe_filename,
        mime_type=attachment.mime_type,
        byte_size=attachment.byte_size,
        sha256=attachment.sha256,
        status=attachment.status,
        status_message=attachment.status_message,
        extraction_result=attachment.extraction_result,
    )


async def _load_conversation(
    session: AsyncSession,
    context: RequestContext,
    conversation_id: int,
) -> AnalyticsConversation:
    conversation = await session.get(AnalyticsConversation, conversation_id)
    if conversation is None or conversation.tenant_id != context.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    if conversation.user_id != context.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized for this conversation",
        )
    return conversation


@router.post("/{conversation_id}", response_model=ChatAttachmentResponse)
async def upload_chat_attachment(
    conversation_id: int,
    file: UploadFile = File(...),
    project_id: int | None = Form(default=None),
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> ChatAttachmentResponse:
    tenant = await session.get(Tenant, context.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    conversation = await _load_conversation(session, context, conversation_id)
    service = get_chat_attachment_service()
    try:
        attachment = await service.upload(
            session,
            tenant,
            context.user_id,
            conversation.id,
            project_id,
            file,
        )
    except ChatAttachmentRejected as exc:
        logger.info("Chat attachment rejected: %s - %s", exc.code, exc.message)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    return _attachment_response(attachment)


@router.get("/{attachment_id}", response_model=ChatAttachmentResponse)
async def get_chat_attachment(
    attachment_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> ChatAttachmentResponse:
    attachment = await session.get(ChatAttachment, attachment_id)
    if attachment is None or attachment.tenant_id != context.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    if attachment.conversation.user_id != context.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
    return _attachment_response(attachment)


@router.delete("/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_chat_attachment(
    attachment_id: int,
    session: AsyncSession = Depends(get_db),
    context: RequestContext = Depends(require_role(Role.VIEWER)),
) -> None:
    service = get_chat_attachment_service()
    deleted = await service.delete(session, context.tenant_id, context.user_id, attachment_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
