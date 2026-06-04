"""Tenant (organization) model.

A tenant is the top-level isolation boundary in the platform. All other rows
carry a `tenant_id` foreign key so middleware can enforce isolation on every
query.
"""

from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Tenant(TimestampMixin, Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    external_id: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    users: Mapped[list[User]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        back_populates="tenant",
        cascade="all, delete-orphan",
    )
    projects: Mapped[list[Project]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        back_populates="tenant",
        cascade="all, delete-orphan",
    )
    user_vdbs: Mapped[list[UserVDB]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        back_populates="tenant",
        cascade="all, delete-orphan",
    )
    shared_vdbs: Mapped[list[SharedVDB]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        back_populates="tenant",
        cascade="all, delete-orphan",
    )
    organization_vdbs: Mapped[list[OrganizationVDB]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        back_populates="tenant",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"Tenant(id={self.id}, slug={self.slug!r})"
