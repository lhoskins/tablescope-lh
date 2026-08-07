"""Tenant enterprise authentication settings (LDAP/SSO toggles and policy)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class TenantEnterpriseAuthSettings(TimestampMixin, Base):
    __tablename__ = "tenant_enterprise_auth_settings"

    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_tenant_enterprise_auth_settings_tenant_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ldap_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sso_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sso_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    local_login_allowed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    sso_provider_id_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    sso_provider_display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sso_provider_entity_id_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sso_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sso_last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sso_last_test_result: Mapped[str | None] = mapped_column(String(512), nullable=True)

    ldap_connection_id: Mapped[int | None] = mapped_column(
        ForeignKey("ldap_connections.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
