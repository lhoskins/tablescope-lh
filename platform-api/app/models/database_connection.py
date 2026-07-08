"""Saved database connection profiles (item 5).

A ``DatabaseConnection`` stores the (encrypted) credentials for an external
database so a user can register several tables from the same database without
re-entering host/port/username/password each time.  It mirrors the role
``ConnectorCredential`` plays for SaaS connectors: one connection profile can
back many ``DatabaseDataSource`` rows.

The password is encrypted at rest with Fernet (see ``app.services.crypto``) and
is never returned to the UI.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class DatabaseConnection(TimestampMixin, Base):
    __tablename__ = "database_connections"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Friendly name shown in the "Connected" dropdown (e.g. "Sales Postgres DB").
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    db_type: Mapped[str] = mapped_column(String(50), nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    database_name: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    # Fernet-encrypted password.  Never returned to the UI.
    password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    ssl_mode: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # When the connection was last verified (on create or via the Test action).
    last_tested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def to_dict(self) -> dict:
        """Serialize for the UI.  Never includes the password."""
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "created_by": self.created_by,
            "name": self.name,
            "db_type": self.db_type,
            "host": self.host,
            "port": self.port,
            "database_name": self.database_name,
            "username": self.username,
            "has_password": bool(self.password_encrypted),
            "ssl_mode": self.ssl_mode,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_tested_at": (
                self.last_tested_at.isoformat() if self.last_tested_at else None
            ),
        }

    def __repr__(self) -> str:
        return (
            f"DatabaseConnection(id={self.id}, name={self.name!r}, "
            f"db_type={self.db_type!r}, host={self.host!r})"
        )
