"""Reference Library models — three-tier governed reference documents.

Tables
------
- ``reference_documents``              — a reference standard/policy at one of three
  tiers (industry / company / project). Industry rows may be metadata-only stubs
  (``file_path is None``) seeded from the starter catalog until a file is uploaded.
- ``reference_document_assignments``   — per-project inheritance / suggestion tracking
  for the hybrid Tier-3 model (inherited / suggested / manually_added / project_unique).
- ``reference_library_import_batches``  — a bulk URL-import job (Industry tier).
- ``reference_library_import_rows``     — one parsed CSV row within an import batch.

Tier / tenant / project scoping is enforced at the API + data-access layer; company and
project rows are never returned across tenant boundaries.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

_JSON = JSONB().with_variant(JSON(), "sqlite")

# Tier values
TIER_INDUSTRY = "industry"
TIER_COMPANY = "company"
TIER_PROJECT = "project"

# Known domain tags (display values). Unknown values map to "Other".
DOMAIN_TAGS: tuple[str, ...] = (
    "Supply Chain & Procurement",
    "Manufacturing & Quality",
    "Finance & Accounting",
    "Legal & Compliance",
    "HR",
    "IT & Cybersecurity",
    "Engineering & Product",
    "Marketing & Sales",
    "ESG",
    "Healthcare",
    "Government & Defense",
    "Other",
)


class ReferenceDocument(TimestampMixin, Base):
    __tablename__ = "reference_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    tier: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )

    title: Mapped[str] = mapped_column(Text, nullable=False)
    issuing_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    domain_tag: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    applicability_tag: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    version_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_verified_at: Mapped[date | None] = mapped_column(Date, nullable=True)

    # active | superseded | draft | processing
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    superseded_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("reference_documents.id", ondelete="SET NULL"), nullable=True
    )

    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    original_filename: Mapped[str | None] = mapped_column(Text, nullable=True)

    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Full per-document AI profile (document_type, business_domain, tags, kpis,
    # entities, suggested_questions, …) — same shape as ProjectAsset.ai_metadata.
    # Never carries a document_family block: families are project-scoped only.
    ai_metadata: Mapped[dict | None] = mapped_column(_JSON, nullable=True)
    extracted_text_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Company-tier: auto-include in every project's Inherited section when true.
    inherit_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    uploaded_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tier": self.tier,
            "tenantId": self.tenant_id,
            "projectId": self.project_id,
            "title": self.title,
            "issuingBody": self.issuing_body,
            "domainTag": self.domain_tag,
            "applicabilityTag": self.applicability_tag,
            "sourceUrl": self.source_url,
            "effectiveDate": self.effective_date.isoformat() if self.effective_date else None,
            "versionLabel": self.version_label,
            "lastVerifiedAt": self.last_verified_at.isoformat() if self.last_verified_at else None,
            "status": self.status,
            "supersededById": self.superseded_by_id,
            "hasFile": bool(self.file_path),
            "fileType": self.file_type,
            "fileSizeBytes": self.file_size_bytes,
            "originalFilename": self.original_filename,
            "aiSummary": self.ai_summary,
            "aiMetadata": self.ai_metadata or {},
            "aiErrorMessage": self.ai_error_message,
            "inheritDefault": self.inherit_default,
            "uploadedBy": self.uploaded_by,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }


class ReferenceDocumentAssignment(TimestampMixin, Base):
    __tablename__ = "reference_document_assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    reference_document_id: Mapped[int] = mapped_column(
        ForeignKey("reference_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # inherited | suggested | manually_added | project_unique
    assignment_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # only for assignment_type == 'suggested': pending | approved | dismissed
    suggestion_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    # false = excluded from this project's AI scope (e.g. inherited doc removed)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    added_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "referenceDocumentId": self.reference_document_id,
            "projectId": self.project_id,
            "assignmentType": self.assignment_type,
            "suggestionStatus": self.suggestion_status,
            "reasoning": self.reasoning,
            "isActive": self.is_active,
            "addedBy": self.added_by,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


class ReferenceAdditionRequest(TimestampMixin, Base):
    """A tenant-admin request to add a standard to the shared Industry catalog."""

    __tablename__ = "reference_addition_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True
    )
    requested_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    issuing_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    domain_tag: Mapped[str | None] = mapped_column(String(100), nullable=True)
    justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    # pending | approved | dismissed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "issuingBody": self.issuing_body,
            "sourceUrl": self.source_url,
            "domainTag": self.domain_tag,
            "justification": self.justification,
            "status": self.status,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


class ReferenceLibraryImportBatch(TimestampMixin, Base):
    __tablename__ = "reference_library_import_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    tier: Mapped[str] = mapped_column(
        String(20), nullable=False, default="industry", server_default="industry"
    )
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    uploaded_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # validating | ready | running | complete | complete_with_errors
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="validating")
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    succeeded_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tier": self.tier,
            "status": self.status,
            "totalRows": self.total_rows,
            "succeededCount": self.succeeded_count,
            "failedCount": self.failed_count,
            "skippedCount": self.skipped_count,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "completedAt": self.completed_at.isoformat() if self.completed_at else None,
        }


class ReferenceLibraryImportRow(TimestampMixin, Base):
    __tablename__ = "reference_library_import_rows"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("reference_library_import_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    issuing_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    domain_tag: Mapped[str | None] = mapped_column(String(100), nullable=True)
    applicability_tag: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    version_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fetch_method_hint: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # pending | fetching | processing | active | failed | skipped
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # informational flags from validation: "duplicate" | "domain_remapped" | ...
    warnings: Mapped[list] = mapped_column(_JSON, nullable=False, default=list)
    will_update_existing_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reference_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("reference_documents.id", ondelete="SET NULL"), nullable=True
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "batchId": self.batch_id,
            "rowNumber": self.row_number,
            "title": self.title,
            "issuingBody": self.issuing_body,
            "domainTag": self.domain_tag,
            "applicabilityTag": self.applicability_tag,
            "sourceUrl": self.source_url,
            "versionLabel": self.version_label,
            "fetchMethodHint": self.fetch_method_hint,
            "status": self.status,
            "failureReason": self.failure_reason,
            "warnings": self.warnings,
            "willUpdateExistingId": self.will_update_existing_id,
            "referenceDocumentId": self.reference_document_id,
        }
