"""SQLAlchemy models for the governed AI reference catalog.

Tables
------
- ai_reference_catalogs  - catalog packs (Tablescope Core, Manufacturing, etc.)
- ai_reference_tags      - governed business tags within a catalog
- ai_reference_kpis      - governed KPI definitions within a catalog
- tenant_reference_catalogs - per-tenant catalog enablement
- tenant_custom_tags     - tenant-created tags
- tenant_custom_kpis     - tenant-created KPIs
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.models.base import Base

_JSON = JSONB().with_variant(JSONB(), "sqlite")


class AIReferenceCatalog(Base):
    __tablename__ = "ai_reference_catalogs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    catalog_key = Column(String(100), nullable=False, unique=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    industry = Column(String(100))
    source_framework = Column(String(255))
    version = Column(String(50), nullable=False, server_default="1.0")
    is_system = Column(Boolean, nullable=False, server_default="true")
    is_active = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    tags = relationship("AIReferenceTag", back_populates="catalog", cascade="all, delete-orphan")
    kpis = relationship("AIReferenceKPI", back_populates="catalog", cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "catalog_key": self.catalog_key,
            "name": self.name,
            "description": self.description,
            "industry": self.industry,
            "source_framework": self.source_framework,
            "version": self.version,
            "is_system": self.is_system,
            "is_active": self.is_active,
        }


class AIReferenceTag(Base):
    __tablename__ = "ai_reference_tags"
    __table_args__ = (UniqueConstraint("catalog_id", "tag_key"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    catalog_id = Column(Integer, ForeignKey("ai_reference_catalogs.id", ondelete="CASCADE"), nullable=False)
    tag_key = Column(String(150), nullable=False)
    display_name = Column(String(255), nullable=False)
    description = Column(Text)
    industry = Column(String(100))
    business_domain = Column(String(100))
    process_area = Column(String(100))
    synonyms = Column(_JSON, nullable=False, server_default="[]")
    related_tags = Column(_JSON, nullable=False, server_default="[]")
    example_fields = Column(_JSON, nullable=False, server_default="[]")
    is_active = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    catalog = relationship("AIReferenceCatalog", back_populates="tags")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "catalog_id": self.catalog_id,
            "tag_key": self.tag_key,
            "display_name": self.display_name,
            "description": self.description,
            "industry": self.industry,
            "business_domain": self.business_domain,
            "process_area": self.process_area,
            "synonyms": self.synonyms or [],
            "related_tags": self.related_tags or [],
            "example_fields": self.example_fields or [],
            "is_active": self.is_active,
        }


class AIReferenceKPI(Base):
    __tablename__ = "ai_reference_kpis"
    __table_args__ = (UniqueConstraint("catalog_id", "kpi_key"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    catalog_id = Column(Integer, ForeignKey("ai_reference_catalogs.id", ondelete="CASCADE"), nullable=False)
    kpi_key = Column(String(150), nullable=False)
    display_name = Column(String(255), nullable=False)
    description = Column(Text)
    industry = Column(String(100))
    business_domain = Column(String(100))
    process_area = Column(String(100))
    formula = Column(Text)
    required_fields = Column(_JSON, nullable=False, server_default="[]")
    optional_fields = Column(_JSON, nullable=False, server_default="[]")
    related_tags = Column(_JSON, nullable=False, server_default="[]")
    recommended_chart_type = Column(String(50))
    recommended_aggregations = Column(_JSON, nullable=False, server_default="[]")
    example_sql_template = Column(Text)
    benchmark_source = Column(String(255))
    is_active = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    catalog = relationship("AIReferenceCatalog", back_populates="kpis")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "catalog_id": self.catalog_id,
            "kpi_key": self.kpi_key,
            "display_name": self.display_name,
            "description": self.description,
            "industry": self.industry,
            "business_domain": self.business_domain,
            "process_area": self.process_area,
            "formula": self.formula,
            "required_fields": self.required_fields or [],
            "optional_fields": self.optional_fields or [],
            "related_tags": self.related_tags or [],
            "recommended_chart_type": self.recommended_chart_type,
            "recommended_aggregations": self.recommended_aggregations or [],
            "example_sql_template": self.example_sql_template,
            "is_active": self.is_active,
        }


class TenantReferenceCatalog(Base):
    __tablename__ = "tenant_reference_catalogs"
    __table_args__ = (UniqueConstraint("tenant_id", "catalog_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    catalog_id = Column(Integer, ForeignKey("ai_reference_catalogs.id", ondelete="CASCADE"), nullable=False)
    is_enabled = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class TenantCustomTag(Base):
    __tablename__ = "tenant_custom_tags"
    __table_args__ = (UniqueConstraint("tenant_id", "tag_key"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    tag_key = Column(String(150), nullable=False)
    display_name = Column(String(255), nullable=False)
    description = Column(Text)
    industry = Column(String(100))
    business_domain = Column(String(100))
    process_area = Column(String(100))
    synonyms = Column(_JSON, nullable=False, server_default="[]")
    related_tags = Column(_JSON, nullable=False, server_default="[]")
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    is_active = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "tag_key": self.tag_key,
            "display_name": self.display_name,
            "description": self.description,
            "business_domain": self.business_domain,
            "process_area": self.process_area,
            "synonyms": self.synonyms or [],
            "is_active": self.is_active,
            "source": "tenant_custom",
        }


class TenantCustomKPI(Base):
    __tablename__ = "tenant_custom_kpis"
    __table_args__ = (UniqueConstraint("tenant_id", "kpi_key"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    kpi_key = Column(String(150), nullable=False)
    display_name = Column(String(255), nullable=False)
    description = Column(Text)
    business_domain = Column(String(100))
    process_area = Column(String(100))
    formula = Column(Text)
    required_fields = Column(_JSON, nullable=False, server_default="[]")
    optional_fields = Column(_JSON, nullable=False, server_default="[]")
    related_tags = Column(_JSON, nullable=False, server_default="[]")
    recommended_chart_type = Column(String(50))
    recommended_aggregations = Column(_JSON, nullable=False, server_default="[]")
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    is_active = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "kpi_key": self.kpi_key,
            "display_name": self.display_name,
            "description": self.description,
            "business_domain": self.business_domain,
            "process_area": self.process_area,
            "formula": self.formula,
            "required_fields": self.required_fields or [],
            "optional_fields": self.optional_fields or [],
            "related_tags": self.related_tags or [],
            "recommended_chart_type": self.recommended_chart_type,
            "is_active": self.is_active,
            "source": "tenant_custom",
        }
