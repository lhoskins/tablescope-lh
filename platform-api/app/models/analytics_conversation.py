"""Conversational analytics persistence.

Multi-turn analytical conversations scoped to a tenant, user, and project.
Each turn stores the user message, classified intent, generated SQL,
execution result cache, chart configuration, and explanation so the UI
can resume and refine a conversation without re-executing prior work.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")


class AnalyticsConversation(Base, TimestampMixin):
    __tablename__ = "analytics_conversations"

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
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="New conversation")
    surface: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ai_assistant", server_default="ai_assistant"
    )
    active_datasource_id: Mapped[int | None] = mapped_column(
        ForeignKey("file_source_meta.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    canonical_key: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    merged_into_conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("analytics_conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_successful_turn_id: Mapped[int | None] = mapped_column(
        ForeignKey("analytics_conversation_turns.id", ondelete="SET NULL"),
        nullable=True,
    )

    turns: Mapped[list[AnalyticsConversationTurn]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="AnalyticsConversationTurn.sequence",
        foreign_keys="AnalyticsConversationTurn.conversation_id",
    )
    last_successful_turn: Mapped[AnalyticsConversationTurn | None] = relationship(
        foreign_keys=[last_successful_turn_id],
    )
    merged_into: Mapped[AnalyticsConversation | None] = relationship(
        "AnalyticsConversation",
        remote_side="AnalyticsConversation.id",
        foreign_keys=[merged_into_conversation_id],
    )

    __table_args__ = (
        sa.Index("ix_analytics_conversations_tenant_user", "tenant_id", "user_id"),
        sa.Index(
            "ix_analytics_conversations_surface_project",
            "tenant_id",
            "user_id",
            "surface",
            "project_id",
        ),
        UniqueConstraint(
            "tenant_id", "user_id", "canonical_key",
            name="uq_analytics_conversations_canonical_key",
        ),
    )


class AnalyticsConversationTurn(Base, TimestampMixin):
    __tablename__ = "analytics_conversation_turns"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("analytics_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(nullable=False)
    client_request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    intent_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    analytical_plan: Mapped[dict[str, Any] | None] = mapped_column(_JSON, nullable=True)
    datasource_context: Mapped[dict[str, Any] | None] = mapped_column(_JSON, nullable=True)
    sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    sql_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_metadata: Mapped[dict[str, Any] | None] = mapped_column(_JSON, nullable=True)
    result_cache: Mapped[dict[str, Any] | None] = mapped_column(_JSON, nullable=True)
    chart_config: Mapped[dict[str, Any] | None] = mapped_column(_JSON, nullable=True)
    explanation: Mapped[dict[str, Any] | None] = mapped_column(_JSON, nullable=True)
    assistant_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_turn_id: Mapped[int | None] = mapped_column(
        ForeignKey("analytics_conversation_turns.id", ondelete="SET NULL"),
        nullable=True,
    )
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    project_context_version: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )

    conversation: Mapped[AnalyticsConversation] = relationship(
        back_populates="turns",
        foreign_keys=[conversation_id],
    )
    parent_turn: Mapped[AnalyticsConversationTurn | None] = relationship(
        remote_side="AnalyticsConversationTurn.id",
        foreign_keys=[parent_turn_id],
    )

    __table_args__ = (
        UniqueConstraint("conversation_id", "sequence", name="uq_analytics_turn_sequence"),
        UniqueConstraint(
            "conversation_id", "client_request_id",
            name="uq_analytics_turn_client_request_id",
        ),
        sa.Index("ix_analytics_turns_status", "status"),
    )
