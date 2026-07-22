"""OrganizationVDB model: organization-wide VDB metadata (template / catalog)."""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class OrganizationVDB(TimestampMixin, Base):
    __tablename__ = "organization_vdbs"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    vdb_name: Mapped[str] = mapped_column(String(255), nullable=False)
    template_vdb_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    vdb_host: Mapped[str] = mapped_column(String(255), default="127.0.0.1", nullable=False)
    vdb_port: Mapped[int] = mapped_column(Integer, default=35442, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    tenant: Mapped[Tenant] = relationship(back_populates="organization_vdbs")  # noqa: F821

    def __repr__(self) -> str:
        return f"OrganizationVDB(id={self.id}, tenant_id={self.tenant_id}, vdb_name={self.vdb_name!r})"
