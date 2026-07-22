"""SQLAlchemy models for the governed Analytical Method Reference Catalog.

This is *governed execution logic*, not Reference/Company Library content: the
catalog defines which statistical methods Tablescope is allowed to run, how each
is selected, and what its result envelope looks like. Uploads never land in the
active executable catalog directly — everything flows through
``draft -> ready_for_review -> approved -> active`` and only ``approved`` +
``active`` records are ever read at runtime.

Tables
------
- method_catalogs            - catalog packs (one per source document)
- method_catalog_versions    - immutable-after-approval version snapshots
- analytical_methods         - per-method entries (cards, rules, contracts)
- analytical_shared_policies - cross-cutting policies (missing data, outliers…)
- method_selection_matrix    - (analysisIntent x data profile) -> method
- method_catalog_audit_log   - every selection / rejection / fallback event

Modeled deliberately on ``ai_reference_catalog.py`` (governed, importable
reference data) rather than inventing a new persistence shape.
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
from sqlalchemy.types import JSON

from app.models.base import Base

_JSON = JSONB().with_variant(JSON(), "sqlite")

# Lifecycle statuses shared by versions and methods.
STATUS_DRAFT = "draft"
STATUS_VALIDATION_FAILED = "validation_failed"
STATUS_READY_FOR_REVIEW = "ready_for_review"
STATUS_APPROVED = "approved"
STATUS_ACTIVE = "active"
STATUS_RETIRED = "retired"


class MethodCatalog(Base):
    __tablename__ = "method_catalogs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    catalog_key = Column(String(100), nullable=False, unique=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    source_document = Column(String(255))
    is_system = Column(Boolean, nullable=False, server_default="true")
    is_active = Column(Boolean, nullable=False, server_default="true")
    active_version_id = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    versions = relationship(
        "MethodCatalogVersion", back_populates="catalog", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "catalog_key": self.catalog_key,
            "name": self.name,
            "description": self.description,
            "source_document": self.source_document,
            "is_system": self.is_system,
            "is_active": self.is_active,
            "active_version_id": self.active_version_id,
        }


class MethodCatalogVersion(Base):
    __tablename__ = "method_catalog_versions"
    __table_args__ = (UniqueConstraint("catalog_id", "version"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    catalog_id = Column(
        Integer, ForeignKey("method_catalogs.id", ondelete="CASCADE"), nullable=False
    )
    version = Column(String(50), nullable=False)
    status = Column(String(30), nullable=False, server_default=STATUS_DRAFT)
    notes = Column(Text)
    method_count = Column(Integer, nullable=False, server_default="0")
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    approved_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    approved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    catalog = relationship("MethodCatalog", back_populates="versions")
    methods = relationship(
        "AnalyticalMethod", back_populates="catalog_version", cascade="all, delete-orphan"
    )
    policies = relationship(
        "AnalyticalSharedPolicy", back_populates="catalog_version", cascade="all, delete-orphan"
    )
    selection_rules = relationship(
        "MethodSelectionMatrix", back_populates="catalog_version", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "catalog_id": self.catalog_id,
            "version": self.version,
            "status": self.status,
            "notes": self.notes,
            "method_count": self.method_count,
        }


class AnalyticalMethod(Base):
    __tablename__ = "analytical_methods"
    __table_args__ = (UniqueConstraint("catalog_version_id", "method_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    catalog_version_id = Column(
        Integer, ForeignKey("method_catalog_versions.id", ondelete="CASCADE"), nullable=False
    )
    method_id = Column(String(150), nullable=False)
    display_name = Column(String(255), nullable=False)
    category = Column(String(150))
    subcategory = Column(String(150))
    tier = Column(Integer, nullable=False, server_default="2")
    status = Column(String(30), nullable=False, server_default=STATUS_DRAFT)

    summary = Column(Text)
    applicability_condition = Column(Text)
    supported_intents = Column(_JSON, nullable=False, server_default="[]")
    selection_rules = Column(_JSON, nullable=False, server_default="[]")
    rejection_rules = Column(_JSON, nullable=False, server_default="[]")
    required_checks = Column(_JSON, nullable=False, server_default="[]")
    fallback_methods = Column(_JSON, nullable=False, server_default="[]")
    output_contract = Column(_JSON, nullable=False, server_default="{}")
    method_card = Column(_JSON, nullable=False, server_default="{}")
    llm_guardrails = Column(_JSON, nullable=False, server_default="[]")
    # Binds an approved+active method to a deterministic executor. NULL
    # means catalogued-but-not-executable (reference only).
    executor_key = Column(String(150), nullable=True)
    execution_engine = Column(String(50), nullable=False, server_default="python")
    result_schema_version = Column(Integer, nullable=False, server_default="1")
    chart_contract = Column(_JSON, nullable=False, server_default="{}")
    max_rows = Column(Integer, nullable=True)
    timeout_seconds = Column(Integer, nullable=True)
    dependencies = Column(_JSON, nullable=False, server_default="[]")
    is_executable = Column(Boolean, nullable=False, server_default="false")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    catalog_version = relationship("MethodCatalogVersion", back_populates="methods")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "method_id": self.method_id,
            "display_name": self.display_name,
            "category": self.category,
            "subcategory": self.subcategory,
            "tier": self.tier,
            "status": self.status,
            "summary": self.summary,
            "applicability_condition": self.applicability_condition,
            "supported_intents": self.supported_intents or [],
            "selection_rules": self.selection_rules or [],
            "rejection_rules": self.rejection_rules or [],
            "required_checks": self.required_checks or [],
            "fallback_methods": self.fallback_methods or [],
            "output_contract": self.output_contract or {},
            "method_card": self.method_card or {},
            "llm_guardrails": self.llm_guardrails or [],
            "executor_key": self.executor_key,
            "execution_engine": self.execution_engine,
            "result_schema_version": self.result_schema_version,
            "chart_contract": self.chart_contract or {},
            "max_rows": self.max_rows,
            "timeout_seconds": self.timeout_seconds,
            "dependencies": self.dependencies or [],
            "is_executable": self.is_executable,
        }


class AnalyticalSharedPolicy(Base):
    __tablename__ = "analytical_shared_policies"
    __table_args__ = (UniqueConstraint("catalog_version_id", "policy_key"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    catalog_version_id = Column(
        Integer, ForeignKey("method_catalog_versions.id", ondelete="CASCADE"), nullable=False
    )
    policy_key = Column(String(100), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    rules = Column(_JSON, nullable=False, server_default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    catalog_version = relationship("MethodCatalogVersion", back_populates="policies")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "policy_key": self.policy_key,
            "name": self.name,
            "description": self.description,
            "rules": self.rules or {},
        }


class MethodSelectionMatrix(Base):
    __tablename__ = "method_selection_matrix"

    id = Column(Integer, primary_key=True, autoincrement=True)
    catalog_version_id = Column(
        Integer, ForeignKey("method_catalog_versions.id", ondelete="CASCADE"), nullable=False
    )
    analysis_intent = Column(String(100), nullable=False)
    data_profile = Column(String(255))
    primary_method_id = Column(String(150), nullable=False)
    alternative_method_ids = Column(_JSON, nullable=False, server_default="[]")
    priority = Column(Integer, nullable=False, server_default="100")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    catalog_version = relationship("MethodCatalogVersion", back_populates="selection_rules")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "analysis_intent": self.analysis_intent,
            "data_profile": self.data_profile,
            "primary_method_id": self.primary_method_id,
            "alternative_method_ids": self.alternative_method_ids or [],
            "priority": self.priority,
        }


class MethodCatalogAuditLog(Base):
    __tablename__ = "method_catalog_audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True)
    catalog_version_id = Column(Integer, nullable=True)
    method_id = Column(String(150), nullable=True)
    event_type = Column(String(50), nullable=False)
    analysis_intent = Column(String(100))
    selected_method = Column(String(150))
    rejected_methods = Column(_JSON, nullable=False, server_default="[]")
    envelope = Column(_JSON, nullable=True)
    reason = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "catalog_version_id": self.catalog_version_id,
            "method_id": self.method_id,
            "event_type": self.event_type,
            "analysis_intent": self.analysis_intent,
            "selected_method": self.selected_method,
            "rejected_methods": self.rejected_methods or [],
            "envelope": self.envelope,
            "reason": self.reason,
        }
