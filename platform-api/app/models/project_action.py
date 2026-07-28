"""Project Action and Subtask models.

Governed action items created from Insight cards (or manually) and their
subtasks.  Actions are soft-deleted, tenant- and project-scoped, and carry a
frozen snapshot of the originating insight plus a content-derived fingerprint
for stable deduplication across AI report regenerations.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

_JSON = JSONB().with_variant(JSON(), "sqlite")


class ProjectAction(TimestampMixin, Base):
    __tablename__ = "project_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="not_started")
    priority: Mapped[str] = mapped_column(String(50), nullable=False, default="medium")
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    percent_complete: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    source_type: Mapped[str] = mapped_column(String(50), nullable=False, default="insight")
    source_insight_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_insight_fingerprint: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    source_insight_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_insight_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_insight_snapshot: Mapped[dict | None] = mapped_column(_JSON, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    lock_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    comments: Mapped[list[ProjectActionComment]] = relationship(
        "ProjectActionComment",
        back_populates="action",
        cascade="all, delete-orphan",
        order_by="ProjectActionComment.created_at.desc()",
    )

    subtasks: Mapped[list[ProjectActionSubtask]] = relationship(
        "ProjectActionSubtask",
        back_populates="action",
        cascade="all, delete-orphan",
        order_by="ProjectActionSubtask.position.asc(), ProjectActionSubtask.id.asc()",
    )

    def __repr__(self) -> str:
        return (
            f"ProjectAction(id={self.id}, project_id={self.project_id}, "
            f"title={self.title!r}, status={self.status!r})"
        )


class ProjectActionSubtask(TimestampMixin, Base):
    __tablename__ = "project_action_subtasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action_id: Mapped[int] = mapped_column(
        ForeignKey("project_actions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="not_started")
    percent_complete: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    is_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    effort_points: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lock_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    action: Mapped[ProjectAction] = relationship("ProjectAction", back_populates="subtasks")

    def __repr__(self) -> str:
        return (
            f"ProjectActionSubtask(id={self.id}, action_id={self.action_id}, "
            f"title={self.title!r}, status={self.status!r})"
        )


class ProjectActionComment(Base, TimestampMixin):
    __tablename__ = "project_action_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action_id: Mapped[int] = mapped_column(
        ForeignKey("project_actions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    action: Mapped[ProjectAction] = relationship("ProjectAction", back_populates="comments")

    def __repr__(self) -> str:
        return (
            f"ProjectActionComment(id={self.id}, action_id={self.action_id}, "
            f"author_user_id={self.author_user_id})"
        )
