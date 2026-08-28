"""UserVDB model: per-user Virtual Database mapping.

Ported from `redash/models/user_vdb.py` (Python 2.7 + Flask-SQLAlchemy) to
SQLAlchemy 2.0 async with explicit `tenant_id` scoping.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class UserVDB(TimestampMixin, Base):
    __tablename__ = "user_vdbs"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    vdb_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    vdb_username: Mapped[str] = mapped_column(String(255), nullable=False)
    encrypted_password: Mapped[str] = mapped_column(String(512), nullable=False)
    vdb_host: Mapped[str] = mapped_column(String(255), default="127.0.0.1", nullable=False)
    vdb_port: Mapped[int] = mapped_column(Integer, default=35442, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    last_health_check: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    health_status: Mapped[str] = mapped_column(String(50), default="unknown", nullable=False)

    tenant: Mapped[Tenant] = relationship(back_populates="user_vdbs")  # type: ignore[name-defined]  # noqa: F821
    user: Mapped[User] = relationship(back_populates="user_vdb")  # type: ignore[name-defined]  # noqa: F821

    def get_connection_string(self) -> str:
        """Return PostgreSQL-style connection string (without credentials).

        Teiid exposes a Postgres-compatible wire protocol. The VDB name must
        include the version suffix: `<vdb_id>.1`.
        """
        vdb_name_with_version = f"{self.vdb_id}.1"
        return f"postgresql://{self.vdb_host}:{self.vdb_port}/{vdb_name_with_version}"

    def get_decrypted_password(self) -> str:
        """Decrypt the stored VDB password.

        TS-ISO-008: this field used to be named "encrypted" but was written
        and returned as plain text. New rows are genuinely Fernet-encrypted
        (see the write sites in tenants_crud.py, tenants_users.py,
        tenant_data_planes_crud.py, tenant_onboarding_service.py,
        project_sharing.py). A row written before this fix still holds
        plaintext, which is not valid Fernet ciphertext and fails to
        decrypt -- fall back to returning it as-is (dual-read) so existing
        connections keep working until the backfill migration re-encrypts
        it; never write plaintext going forward.
        """
        from app.services.crypto import decrypt_secret

        try:
            return decrypt_secret(self.encrypted_password)
        except Exception:
            return self.encrypted_password

    def to_dict(self, include_credentials: bool = False) -> dict:
        data: dict = {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
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
        return f"UserVDB(id={self.id}, user_id={self.user_id}, vdb_id={self.vdb_id!r})"
