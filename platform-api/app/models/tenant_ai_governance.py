"""Tenant-level AI governance policy models.

A tenant administrator can enable or disable analytical methods for their
organization.  The policy is a shallow wrapper around per-method overrides; the
system default is read from the analytical method registry so existing tenants
are not broken by the migration.
"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class TenantAIGovernancePolicy(TimestampMixin, Base):
    """One active policy row per tenant."""

    __tablename__ = "tenant_ai_governance_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    method_policies: Mapped[list[TenantAIMethodPolicy]] = relationship(
        back_populates="policy",
        cascade="all, delete-orphan",
    )


class TenantAIMethodPolicy(TimestampMixin, Base):
    """Per-tenant override for a single analytical method."""

    __tablename__ = "tenant_ai_method_policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", "method_key"),
        Index("ix_tenant_ai_method_policy_tenant_method", "tenant_id", "method_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    policy_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tenant_ai_governance_policies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    method_key: Mapped[str] = mapped_column(String(150), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    updated_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    policy: Mapped[TenantAIGovernancePolicy] = relationship(
        back_populates="method_policies"
    )
