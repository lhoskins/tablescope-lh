"""User model with tenant scoping."""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    external_id: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True, index=True
    )
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(32), default="viewer", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    tenant: Mapped[Tenant] = relationship(back_populates="users")  # type: ignore[name-defined]  # noqa: F821
    owned_projects: Mapped[list[Project]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        back_populates="owner",
        foreign_keys="Project.owner_id",
    )
    user_vdb: Mapped[UserVDB | None] = relationship(  # type: ignore[name-defined]  # noqa: F821
        back_populates="user",
        uselist=False,
    )

    __table_args__ = (
        # Email is unique per tenant, not globally.
        # A composite unique constraint is added in the migration.
    )

    def __repr__(self) -> str:
        return f"User(id={self.id}, tenant_id={self.tenant_id}, email={self.email!r})"
