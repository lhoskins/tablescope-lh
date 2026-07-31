"""Home pins — durable frozen insight snapshots and live widget references.

A pin belongs to one user/tenant. Two kinds are supported:

* ``insight_card`` — a frozen snapshot of an AI-generated insight card. The
  payload is stored in ``frozen_payload`` and never refreshed.
* ``live_widget`` — a reference to a dashboard widget (project + dashboard +
  widget config) that refreshes safely on demand.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

_JSON = JSONB().with_variant(JSON(), "sqlite")


class HomePin(TimestampMixin, Base):
    __tablename__ = "home_pins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    pin_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )
    pin_key: Mapped[str] = mapped_column(String(255), nullable=False)
    destination: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="home",
        server_default=text("'home'"),
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    config: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict)
    layout: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict)
    frozen_payload: Mapped[dict | None] = mapped_column(_JSON, nullable=True)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(
        nullable=True,
        default=None,
    )
    refresh_error: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )
    is_pinned: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "user_id",
            "pin_key",
            "destination",
            name="uix_home_pins_tenant_user_key_destination",
        ),
    )
