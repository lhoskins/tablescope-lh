"""User model with tenant scoping."""

from __future__ import annotations

from passlib.context import CryptContext
from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    # Identity is unique *per tenant* (see uq_users_tenant_external_id below), so
    # one Supabase email can map to a user in several tenants.
    external_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    # Supabase Auth subject id (mirrors external_id when Supabase is the IdP).
    supabase_user_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="viewer", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_super_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)

    tenant: Mapped[Tenant] = relationship(back_populates="users")  # type: ignore[name-defined]  # noqa: F821
    owned_projects: Mapped[list[Project]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        back_populates="owner",
        foreign_keys="Project.owner_id",
    )
    user_vdb: Mapped[UserVDB | None] = relationship(  # type: ignore[name-defined]  # noqa: F821
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        # Email + identity are unique per tenant, not globally. The
        # (tenant_id, email) constraint is created in the initial migration.
        UniqueConstraint(
            "tenant_id", "external_id", name="uq_users_tenant_external_id"
        ),
        UniqueConstraint(
            "tenant_id", "supabase_user_id", name="uq_users_tenant_supabase"
        ),
    )

    def set_password(self, plain: str) -> None:
        self.password_hash = _pwd_context.hash(plain)

    def verify_password(self, plain: str) -> bool:
        if not self.password_hash:
            return False
        return _pwd_context.verify(plain, self.password_hash)

    def __repr__(self) -> str:
        return f"User(id={self.id}, tenant_id={self.tenant_id}, email={self.email!r})"
