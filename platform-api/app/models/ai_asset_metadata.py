"""SQLAlchemy models for AI asset metadata - tag/KPI suggestions and accepted values.

Tables
------
- ai_asset_tag_suggestions  - AI-suggested tags (suggested/accepted/rejected)
- ai_asset_tags             - accepted tags for an asset
- ai_asset_kpi_suggestions  - AI-suggested KPIs (suggested/accepted/rejected)
- ai_asset_kpis             - accepted KPIs for an asset
"""

from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.models.base import Base

_JSON = JSONB().with_variant(JSONB(), "sqlite")


class AIAssetTagSuggestion(Base):
    __tablename__ = "ai_asset_tag_suggestions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    source_type = Column(String(100), nullable=False)
    source_id = Column(Integer, nullable=False)
    tag_key = Column(String(150), nullable=False)
    display_name = Column(String(255), nullable=False)
    confidence = Column(Numeric(5, 4))
    reason = Column(Text)
    status = Column(String(50), nullable=False, server_default="suggested")
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tag_key": self.tag_key,
            "display_name": self.display_name,
            "confidence": float(self.confidence) if self.confidence else None,
            "reason": self.reason,
            "status": self.status,
            "source": "ai_suggested",
        }


class AIAssetTag(Base):
    __tablename__ = "ai_asset_tags"
    __table_args__ = (
        UniqueConstraint("tenant_id", "project_id", "source_type", "source_id", "tag_key"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    source_type = Column(String(100), nullable=False)
    source_id = Column(Integer, nullable=False)
    tag_key = Column(String(150), nullable=False)
    display_name = Column(String(255), nullable=False)
    business_domain = Column(String(100))
    process_area = Column(String(100))
    confidence = Column(Numeric(5, 4))
    source = Column(String(50), nullable=False, server_default="ai_suggested")
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tag_key": self.tag_key,
            "display_name": self.display_name,
            "business_domain": self.business_domain,
            "process_area": self.process_area,
            "confidence": float(self.confidence) if self.confidence else None,
            "source": self.source,
        }


class AIAssetKPISuggestion(Base):
    __tablename__ = "ai_asset_kpi_suggestions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    source_type = Column(String(100), nullable=False)
    source_id = Column(Integer, nullable=False)
    kpi_key = Column(String(150), nullable=False)
    display_name = Column(String(255), nullable=False)
    confidence = Column(Numeric(5, 4))
    field_mapping = Column(_JSON, nullable=False, server_default="{}")
    formula = Column(Text)
    recommended_chart_type = Column(String(50))
    reason = Column(Text)
    status = Column(String(50), nullable=False, server_default="suggested")
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kpi_key": self.kpi_key,
            "display_name": self.display_name,
            "confidence": float(self.confidence) if self.confidence else None,
            "field_mapping": self.field_mapping or {},
            "formula": self.formula,
            "recommended_chart_type": self.recommended_chart_type,
            "reason": self.reason,
            "status": self.status,
            "source": "ai_suggested",
        }


class AIAssetKPI(Base):
    __tablename__ = "ai_asset_kpis"
    __table_args__ = (
        UniqueConstraint("tenant_id", "project_id", "source_type", "source_id", "kpi_key"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    source_type = Column(String(100), nullable=False)
    source_id = Column(Integer, nullable=False)
    kpi_key = Column(String(150), nullable=False)
    display_name = Column(String(255), nullable=False)
    field_mapping = Column(_JSON, nullable=False, server_default="{}")
    formula = Column(Text)
    recommended_chart_type = Column(String(50))
    confidence = Column(Numeric(5, 4))
    source = Column(String(50), nullable=False, server_default="ai_suggested")
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kpi_key": self.kpi_key,
            "display_name": self.display_name,
            "field_mapping": self.field_mapping or {},
            "formula": self.formula,
            "recommended_chart_type": self.recommended_chart_type,
            "confidence": float(self.confidence) if self.confidence else None,
            "source": self.source,
        }
