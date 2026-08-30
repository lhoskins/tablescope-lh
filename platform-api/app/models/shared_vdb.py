"""SharedVDB model: per-(tenant, project) shared Virtual Database mapping.

Loosely modeled on `redash/models/shared_vdb.py` (which was itself
per-organization, not per-project -- see migration 0087's docstring for why
this diverges from that legacy shape).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class SharedVDB(TimestampMixin, Base):
    """One shared VDB per (tenant, project) -- scoped per project, not per
    tenant. A tenant with several shared projects gets a separate row (and a
    separate physical VDB/folder) for each; two shared projects never land
    in the same VDB. ``project_id`` is nullable only so the pre-migration
    per-tenant rows (from before this scoping existed) are not backfilled or
    deleted -- see migration 0087."""

    __tablename__ = "shared_vdbs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "project_id", name="uq_shared_vdbs_tenant_project"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    vdb_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    vdb_username: Mapped[str] = mapped_column(String(255), nullable=False)
    encrypted_password: Mapped[str] = mapped_column(String(512), nullable=False)
    vdb_host: Mapped[str] = mapped_column(String(255), default="127.0.0.1", nullable=False)
    vdb_port: Mapped[int] = mapped_column(Integer, default=35442, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    last_health_check: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    health_status: Mapped[str] = mapped_column(String(50), default="unknown", nullable=False)

    tenant: Mapped[Tenant] = relationship(back_populates="shared_vdbs")  # type: ignore[name-defined]  # noqa: F821

    def get_connection_string(self) -> str:
        vdb_name_with_version = f"{self.vdb_id}.1"
        return f"postgresql://{self.vdb_host}:{self.vdb_port}/{vdb_name_with_version}"

    def get_decrypted_password(self) -> str:
        """Decrypt the stored VDB password (TS-ISO-008) -- see
        UserVDB.get_decrypted_password's docstring for the full rationale
        of the plaintext-fallback dual-read."""
        from app.services.crypto import decrypt_secret

        try:
            return decrypt_secret(self.encrypted_password)
        except Exception:
            return self.encrypted_password

    def to_dict(self, include_credentials: bool = False) -> dict:
        data: dict = {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "vdb_id": self.vdb_id,
            "vdb_host": self.vdb_host,
            "vdb_port": self.vdb_port,
            "is_active": self.is_active,
            "health_status": self.health_status,
            "last_health_check": self.last_health_check.isoformat() if self.last_health_check else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_credentials:
            data["vdb_username"] = self.vdb_username
        return data

    def __repr__(self) -> str:
        return f"SharedVDB(id={self.id}, tenant_id={self.tenant_id}, vdb_id={self.vdb_id!r})"
