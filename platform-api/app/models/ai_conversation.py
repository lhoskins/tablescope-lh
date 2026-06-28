"""AI conversation models — saved chat threads for the Home AI Assistant.

Conversations are scoped to a tenant and owned by a user. They optionally
reference a project to scope the AI's answers. Each conversation has an ordered
list of messages (user / assistant).
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class AiConversation(TimestampMixin, Base):
    __tablename__ = "ai_conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(
        String(255), nullable=False, default="New conversation"
    )
    # Conversation branching: a sub-chat forked from a point in another
    # conversation. ``parent_conversation_id`` is the source thread and
    # ``branched_from_message_id`` is the message the branch diverged from.
    parent_conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    branched_from_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_conversation_messages.id", ondelete="SET NULL"),
        nullable=True,
    )

    messages: Mapped[list[AiConversationMessage]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="AiConversationMessage.id",
        foreign_keys="AiConversationMessage.conversation_id",
    )

    def __repr__(self) -> str:
        return f"AiConversation(id={self.id}, title={self.title!r})"


class AiConversationMessage(TimestampMixin, Base):
    __tablename__ = "ai_conversation_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("ai_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")

    conversation: Mapped[AiConversation] = relationship(
        back_populates="messages",
        foreign_keys=[conversation_id],
    )

    def __repr__(self) -> str:
        return (
            f"AiConversationMessage(id={self.id}, "
            f"conversation_id={self.conversation_id}, role={self.role!r})"
        )
