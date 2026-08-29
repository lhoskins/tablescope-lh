"""Workspace models — named, multi-card canvases inside a project.

A workspace is a user-created canvas holding an arbitrary number of cards,
each pointing at an existing table, dashboard, document, or data source.
Sharing follows the ``project_asset`` pattern: private by default, owned by
its creator, publishable to the rest of the project.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Workspace(TimestampMixin, Base):
    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    visibility: Mapped[str] = mapped_column(String(50), nullable=False, default="private")
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    def __repr__(self) -> str:
        return f"Workspace(id={self.id}, name={self.name!r}, visibility={self.visibility!r})"


class WorkspaceCard(Base):
    __tablename__ = "workspace_cards"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # Kept as a string so it matches the id shape the frontend WorkspaceTab
    # already uses; grounding converts it to a numeric id per resource type.
    resource_id: Mapped[str] = mapped_column(String, nullable=False)
    view_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="card")
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"WorkspaceCard(id={self.id}, workspace_id={self.workspace_id}, "
            f"resource_type={self.resource_type!r}, resource_id={self.resource_id!r})"
        )
