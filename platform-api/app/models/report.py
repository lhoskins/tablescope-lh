"""Report model — Live Report Builder definitions (query defs, not data)."""

from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

_JSON = JSONB().with_variant(JSON(), "sqlite")


class Report(TimestampMixin, Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Public share token used in /reports/{token} URLs.
    share_token: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False, default="Untitled report")
    # List of report sections: insight cards (query definitions) + text blocks.
    sections: Mapped[list] = mapped_column(_JSON, nullable=False, default=list)
    # { isPublic, viewerIds, pdfSnapshotAvailable }
    share_settings: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict)
