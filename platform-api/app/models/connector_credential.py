"""Connector credential model.

A ``ConnectorCredential`` stores the (encrypted) authentication material for a
SaaS connector — e.g. a HubSpot Private App token or a Salesforce OAuth
credential bundle.  One credential can back several SaaS data sources (e.g. a
single HubSpot token used for Contacts, Companies and Deals), which is why it is
modelled separately from the per-object source row.

The secret is encrypted at rest with Fernet (see ``app.services.crypto``) and is
never returned to the UI.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ConnectorCredential(TimestampMixin, Base):
    __tablename__ = "connector_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    connector_type: Mapped[str] = mapped_column(String(50), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Fernet-encrypted JSON blob of the connector's auth config.  For HubSpot
    # this is ``{"access_token": "..."}``; for Salesforce the OAuth bundle.
    # Never returned to the UI.
    secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Non-secret config kept in the clear for display/refresh (e.g. Salesforce
    # instance_url, client_id).  Never contains the password/secret/token.
    config_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # When the credential was last verified (on create or via the Test action).
    last_tested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "created_by": self.created_by,
            "connector_type": self.connector_type,
            "display_name": self.display_name,
            "has_secret": bool(self.secret_encrypted),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_tested_at": (
                self.last_tested_at.isoformat() if self.last_tested_at else None
            ),
        }

    def __repr__(self) -> str:
        return (
            f"ConnectorCredential(id={self.id}, "
            f"connector_type={self.connector_type!r}, "
            f"display_name={self.display_name!r})"
        )
