"""Tenant membership + Supabase auth binding models.

`tenant_memberships` decouples user↔tenant from the legacy single
`users.tenant_id` column so a user can hold a role (root_admin/admin/editor/
viewer) in a tenant. `tenant_auth_bindings` records the mapping between a
Supabase Auth user and the Tablescope tenant/user.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

MEMBERSHIP_ROLES = ("root_admin", "admin", "editor", "viewer")


class TenantMembership(TimestampMixin, Base):
    __tablename__ = "tenant_memberships"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(32), default="viewer", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_tenant_membership_tenant_user"),
    )

    def __repr__(self) -> str:
        return (
            f"TenantMembership(tenant_id={self.tenant_id}, user_id={self.user_id}, "
            f"role={self.role!r})"
        )


class TenantAuthBinding(TimestampMixin, Base):
    __tablename__ = "tenant_auth_bindings"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), default="supabase", nullable=False)
    supabase_user_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
    email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "provider", "supabase_user_id", name="uq_auth_binding_provider_subject"
        ),
    )

    def __repr__(self) -> str:
        return (
            f"TenantAuthBinding(supabase_user_id={self.supabase_user_id!r}, "
            f"tenant_id={self.tenant_id})"
        )
