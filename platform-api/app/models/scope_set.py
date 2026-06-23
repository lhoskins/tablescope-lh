"""Scope set model — a named, toggleable group of query scopes.

A scope set is the parent object users manage on the Scope Navigation page.
Each set owns a collection of :class:`QueryScope` field mappings plus the
canvas layout that the Scope Relationship Builder renders.  Disabling a set
disables every drill-down it contains without deleting the mappings.
"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

SCOPE_SET_TYPES = ("ai_generated", "manual")


class ScopeSet(TimestampMixin, Base):
    __tablename__ = "scope_sets"

    id: Mapped[int] = mapped_column(primary_key=True)
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
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # "ai_generated" | "manual"
    type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="manual", server_default="manual"
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_by: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    def to_dict(
        self,
        scope_count: int | None = None,
        *,
        creator_name: str | None = None,
        creator_email: str | None = None,
        can_delete: bool | None = None,
    ) -> dict:
        data: dict = {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "name": self.name,
            "description": self.description,
            "type": self.type,
            "enabled": self.enabled,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "creator_name": creator_name,
            "creator_email": creator_email,
        }
        if scope_count is not None:
            data["scope_count"] = scope_count
        if can_delete is not None:
            data["can_delete"] = can_delete
        return data

    def __repr__(self) -> str:
        return (
            f"ScopeSet(id={self.id}, project_id={self.project_id}, "
            f"name={self.name!r}, type={self.type!r}, enabled={self.enabled})"
        )
