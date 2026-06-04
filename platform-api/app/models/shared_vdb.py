"""SharedVDB model: per-tenant shared Virtual Database mapping.

Ported from `redash/models/shared_vdb.py` to SQLAlchemy 2.0 async.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class SharedVDB(TimestampMixin, Base):
    __tablename__ = "shared_vdbs"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
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
