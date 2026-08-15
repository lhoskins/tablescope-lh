"""Persistent dashboard groups and approved template-to-data bindings."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

_JSON = JSONB().with_variant(JSON(), "sqlite")


class DashboardGroup(TimestampMixin, Base):
    __tablename__ = "dashboard_groups"
    __table_args__ = (UniqueConstraint("tenant_id", "project_id", "slug", name="uq_dashboard_group_project_slug"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    icon: Mapped[str] = mapped_column(String(50), nullable=False, default="activity")
    template_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    collapsed_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class DashboardTemplateBinding(TimestampMixin, Base):
    __tablename__ = "dashboard_template_bindings"
    __table_args__ = (UniqueConstraint("tenant_id", "project_id", "template_id", "group_key", "version", name="uq_dashboard_template_binding_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    dashboard_group_id: Mapped[int | None] = mapped_column(ForeignKey("dashboard_groups.id", ondelete="SET NULL"), nullable=True, index=True)
    template_id: Mapped[str] = mapped_column(String(255), nullable=False)
    template_name: Mapped[str] = mapped_column(String(255), nullable=False)
    template_version: Mapped[str] = mapped_column(String(50), nullable=False, default="1")
    group_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft", index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    dimension_config: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict)
    source_mapping: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict)
    field_mapping: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict)
    joins: Mapped[list] = mapped_column(_JSON, nullable=False, default=list)
    metric_manifest: Mapped[list] = mapped_column(_JSON, nullable=False, default=list)
    validation: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DashboardTemplateQuery(TimestampMixin, Base):
    __tablename__ = "dashboard_template_queries"
    __table_args__ = (UniqueConstraint("binding_id", "query_key", "version", name="uq_dashboard_template_query_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    binding_id: Mapped[int] = mapped_column(ForeignKey("dashboard_template_bindings.id", ondelete="CASCADE"), index=True)
    saved_query_id: Mapped[int | None] = mapped_column(ForeignKey("saved_queries.id", ondelete="SET NULL"), nullable=True)
    query_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="compiled")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sql_template: Mapped[str] = mapped_column(Text, nullable=False)
    compiled_sql: Mapped[str] = mapped_column(Text, nullable=False)
    dashboard_keys: Mapped[list] = mapped_column(_JSON, nullable=False, default=list)
    metric_keys: Mapped[list] = mapped_column(_JSON, nullable=False, default=list)
    lineage: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict)
    validation: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict)
    cache_ttl_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300, server_default="300")
