from __future__ import annotations

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ProjectBusinessContext(TimestampMixin, Base):
    """Project-level settings and business context.

    Kept separate from :class:`Project` so existing projects stay compatible
    and context can be added lazily.
    """

    __tablename__ = "project_business_contexts"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    business_owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    business_function: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    industry: Mapped[str | None] = mapped_column(String(255), nullable=True)
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    timezone: Mapped[str] = mapped_column(String(100), nullable=False, default="UTC")
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="USD")
    reporting_cadence: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # e.g. weekly, monthly, quarterly, annual
    fiscal_year_start_month: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    ai_context_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    ai_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    interpretation_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        Index("ix_project_business_context_tenant_project", "tenant_id", "project_id"),
    )

    def to_redacted_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "business_owner_id": self.business_owner_id,
            "business_function": self.business_function,
            "industry": self.industry,
            "purpose": self.purpose,
            "timezone": self.timezone,
            "currency": self.currency,
            "reporting_cadence": self.reporting_cadence,
            "fiscal_year_start_month": self.fiscal_year_start_month,
            "ai_context_enabled": self.ai_context_enabled,
            "ai_instructions": self.ai_instructions,
            "interpretation_notes": self.interpretation_notes,
            "version": self.version,
            "updated_by": self.updated_by,
        }
