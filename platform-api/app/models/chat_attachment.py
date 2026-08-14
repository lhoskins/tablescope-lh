"""Chat attachment model for AI Assistant file/image uploads.

Attachments are tenant- and conversation-scoped. They are uploaded before being
linked to a message; once a turn is submitted, ``message_id`` is set. Storage
paths are opaque to the client; content extraction results are kept in
``extraction_result`` for prompt assembly.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")


class ChatAttachment(TimestampMixin, Base):
    __tablename__ = "chat_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("analytics_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("analytics_conversation_turns.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    uploaded_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    safe_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    byte_size: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="uploading"
    )
    status_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_result: Mapped[dict[str, Any] | None] = mapped_column(_JSON, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    conversation: Mapped[AnalyticsConversation] = relationship(  # type: ignore[name-defined]  # noqa: F821
        back_populates="chat_attachments",
        foreign_keys=[conversation_id],
    )
    message: Mapped[AnalyticsConversationTurn | None] = relationship(  # type: ignore[name-defined]  # noqa: F821
        back_populates="chat_attachments",
        foreign_keys=[message_id],
    )
