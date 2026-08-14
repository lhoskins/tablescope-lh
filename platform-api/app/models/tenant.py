"""Tenant (organization) model.

A tenant is the top-level isolation boundary in the platform. All other rows
carry a `tenant_id` foreign key so middleware can enforce isolation on every
query.
"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Tenant(TimestampMixin, Base):
    __tablename__ = "tenants"

    # A slug is only reserved while its tenant is active. Deleting (hard delete)
    # or deactivating a tenant frees the slug for reuse, enforced by a partial
    # unique index rather than a plain unique constraint.
    __table_args__ = (
        Index(
            "uq_tenants_slug_active",
            "slug",
            unique=True,
            postgresql_where=text("is_active"),
            sqlite_where=text("is_active"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    external_id: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # When true, every member of the tenant (not just admin/privileged roles) must
    # complete SMS MFA before accessing tenant data. Admins are always required
    # when the platform MFA master switch is on; this flag extends that requirement
    # to all roles. Default off so it is an explicit tenant decision.
    enforce_2fa: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=text("false")
    )
    # When true, only users whose email domain is on the allowed list (plus the
    # tenant owner/admins) may sign up, be invited, receive mail, or sign in.
    allowed_domains_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=text("false")
    )
    # When true, microphone/audio input is surfaced in AI composers for this tenant.
    voice_input_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=text("false")
    )
    # When true, users can attach images and files to AI Assistant messages.
    # Controlled by the CHAT_ATTACHMENTS_V1 feature gate.
    chat_attachments_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=text("false")
    )
    # The original tenant admin / owner — always exempt from domain restriction
    # so an admin can never lock themselves out.
    owner_user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Admin-uploaded company logo (tenant/customer branding shown in the top
    # header). ``logo_url`` is the opaque served URL; ``logo_file_id`` locates
    # the image on disk / in S3. Distinct from the static Tablescope product logo.
    logo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    logo_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    allowed_domains: Mapped[list[TenantAllowedDomain]] = relationship(
        back_populates="tenant",
        cascade="all, delete-orphan",
    )

    users: Mapped[list[User]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        back_populates="tenant",
        cascade="all, delete-orphan",
        foreign_keys="User.tenant_id",
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


class TenantAllowedDomain(TimestampMixin, Base):
    """A single email domain allowed to access a tenant (when restriction is on)."""

    __tablename__ = "tenant_allowed_domains"

    __table_args__ = (
        Index(
            "uq_tenant_allowed_domain",
            "tenant_id",
            "domain",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default=text("true")
    )
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)

    tenant: Mapped[Tenant] = relationship(back_populates="allowed_domains")

    def __repr__(self) -> str:
        return (
            f"TenantAllowedDomain(id={self.id}, tenant_id={self.tenant_id}, "
            f"domain={self.domain!r})"
        )
