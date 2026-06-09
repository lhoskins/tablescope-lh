"""AI-assisted file analysis metadata models.

Stores AI-generated profiles, field-level metadata, tags, and
recommendations produced during the enhanced file upload wizard.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

# JSONB on Postgres, plain JSON on other dialects (e.g. SQLite in tests).
_JSON = JSONB().with_variant(JSON(), "sqlite")


class DataSourceAIProfile(TimestampMixin, Base):
    """Top-level AI analysis profile for an uploaded data source."""

    __tablename__ = "data_source_ai_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    data_source_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )

    file_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    column_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sheet_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_usage_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_quality_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    user_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_nuances: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="draft"
    )
    analysis_version: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="v1"
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "data_source_id": self.data_source_id,
            "project_id": self.project_id,
            "file_name": self.file_name,
            "file_type": self.file_type,
            "file_size_bytes": self.file_size_bytes,
            "row_count": self.row_count,
            "column_count": self.column_count,
            "sheet_name": self.sheet_name,
            "ai_summary": self.ai_summary,
            "ai_usage_summary": self.ai_usage_summary,
            "ai_quality_summary": self.ai_quality_summary,
            "user_notes": self.user_notes,
            "user_nuances": self.user_nuances,
            "status": self.status,
            "analysis_version": self.analysis_version,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class DataSourceFieldProfile(TimestampMixin, Base):
    """Per-field profiling and AI-generated metadata."""

    __tablename__ = "data_source_field_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    data_source_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_source_ai_profiles.id", ondelete="CASCADE"), nullable=True
    )

    field_name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    detected_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    recommended_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    max_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_length: Mapped[int | None] = mapped_column(Integer, nullable=True)

    nullable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    null_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    null_percent: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    distinct_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    sample_values: Mapped[list[Any] | None] = mapped_column(_JSON, nullable=True)
    min_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_value: Mapped[str | None] = mapped_column(Text, nullable=True)

    ai_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_quality_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    include_in_ai: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "data_source_id": self.data_source_id,
            "profile_id": self.profile_id,
            "field_name": self.field_name,
            "display_name": self.display_name,
            "detected_type": self.detected_type,
            "recommended_type": self.recommended_type,
            "max_length": self.max_length,
            "min_length": self.min_length,
            "nullable": self.nullable,
            "null_count": self.null_count,
            "null_percent": float(self.null_percent) if self.null_percent is not None else None,
            "distinct_count": self.distinct_count,
            "sample_values": self.sample_values,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "ai_description": self.ai_description,
            "ai_quality_notes": self.ai_quality_notes,
            "user_notes": self.user_notes,
            "include_in_ai": self.include_in_ai,
        }


class DataSourceTag(Base):
    """Tags (AI-generated or user-created) for a data source."""

    __tablename__ = "data_source_tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    data_source_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )

    tag: Mapped[str] = mapped_column(String(100), nullable=False)
    tag_type: Mapped[str] = mapped_column(String(50), nullable=False, server_default="user")
    source: Mapped[str] = mapped_column(String(50), nullable=False, server_default="user")

    confidence: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "data_source_id": self.data_source_id,
            "tag": self.tag,
            "tag_type": self.tag_type,
            "source": self.source,
            "confidence": float(self.confidence) if self.confidence is not None else None,
            "accepted": self.accepted,
        }


class DataSourceAIRecommendation(TimestampMixin, Base):
    """AI-generated recommendations the user can accept or reject."""

    __tablename__ = "data_source_ai_recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    data_source_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_source_ai_profiles.id", ondelete="CASCADE"), nullable=True
    )

    recommendation_type: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(50), nullable=False, server_default="info")

    suggested_action: Mapped[dict[str, Any] | None] = mapped_column(_JSON, nullable=True)

    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="pending")
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "data_source_id": self.data_source_id,
            "profile_id": self.profile_id,
            "recommendation_type": self.recommendation_type,
            "title": self.title,
            "description": self.description,
            "severity": self.severity,
            "suggested_action": self.suggested_action,
            "status": self.status,
        }
