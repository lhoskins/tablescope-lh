"""Project + ProjectMember models with tenant scoping.

Ported from `redash/models/project.py` to SQLAlchemy 2.0 async with
`tenant_id` for multi-tenant isolation.
"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    scoping_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="false")

    tenant: Mapped[Tenant] = relationship(back_populates="projects")  # type: ignore[name-defined]  # noqa: F821
    owner: Mapped[User | None] = relationship(  # type: ignore[name-defined]  # noqa: F821
        back_populates="owned_projects",
        foreign_keys=[owner_id],
    )
    members: Mapped[list[ProjectMember]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"Project(id={self.id}, tenant_id={self.tenant_id}, name={self.name!r})"


class ProjectMember(Base):
    __tablename__ = "project_members"

    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[str] = mapped_column(String(50), default="member", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    project: Mapped[Project] = relationship(back_populates="members")

    def __repr__(self) -> str:
        return f"ProjectMember(project_id={self.project_id}, user_id={self.user_id}, role={self.role!r}, active={self.is_active})"
