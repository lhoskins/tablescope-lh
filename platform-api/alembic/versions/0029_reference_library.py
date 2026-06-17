"""Reference Library: three-tier reference documents + bulk URL import.

Adds:
- ``reference_documents`` — reference standards/policies at industry/company/project tiers.
- ``reference_document_assignments`` — per-project inheritance/suggestion tracking.
- ``reference_library_import_batches`` — bulk URL-import jobs (Industry tier).
- ``reference_library_import_rows`` — parsed CSV rows within an import batch.

Revision ID: 0029
Revises: 0028
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")


def _tables(conn: sa.engine.Connection) -> set[str]:
    return set(sa.inspect(conn).get_table_names())


def upgrade() -> None:
    conn = op.get_bind()
    existing = _tables(conn)

    if "reference_documents" not in existing:
        op.create_table(
            "reference_documents",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tier", sa.String(length=20), nullable=False),
            sa.Column(
                "tenant_id",
                sa.Integer(),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column(
                "project_id",
                sa.Integer(),
                sa.ForeignKey("projects.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("issuing_body", sa.Text(), nullable=True),
            sa.Column("domain_tag", sa.String(length=100), nullable=True),
            sa.Column("applicability_tag", sa.String(length=100), nullable=True),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("effective_date", sa.Date(), nullable=True),
            sa.Column("version_label", sa.String(length=255), nullable=True),
            sa.Column("last_verified_at", sa.Date(), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
            sa.Column(
                "superseded_by_id",
                sa.Integer(),
                sa.ForeignKey("reference_documents.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("file_path", sa.Text(), nullable=True),
            sa.Column("file_type", sa.String(length=20), nullable=True),
            sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
            sa.Column("original_filename", sa.Text(), nullable=True),
            sa.Column("ai_summary", sa.Text(), nullable=True),
            sa.Column("extracted_text_path", sa.Text(), nullable=True),
            sa.Column("ai_error_message", sa.Text(), nullable=True),
            sa.Column(
                "inherit_default", sa.Boolean(), nullable=False, server_default="false"
            ),
            sa.Column(
                "uploaded_by",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
        op.create_index("ix_reference_documents_tier", "reference_documents", ["tier"])
        op.create_index(
            "ix_reference_documents_tenant_id", "reference_documents", ["tenant_id"]
        )
        op.create_index(
            "ix_reference_documents_project_id", "reference_documents", ["project_id"]
        )
        op.create_index(
            "ix_reference_documents_domain_tag", "reference_documents", ["domain_tag"]
        )

    if "reference_document_assignments" not in existing:
        op.create_table(
            "reference_document_assignments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "reference_document_id",
                sa.Integer(),
                sa.ForeignKey("reference_documents.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "project_id",
                sa.Integer(),
                sa.ForeignKey("projects.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("assignment_type", sa.String(length=30), nullable=False),
            sa.Column("suggestion_status", sa.String(length=20), nullable=True),
            sa.Column("reasoning", sa.Text(), nullable=True),
            sa.Column(
                "is_active", sa.Boolean(), nullable=False, server_default="true"
            ),
            sa.Column(
                "added_by",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
        op.create_index(
            "ix_reference_document_assignments_doc",
            "reference_document_assignments",
            ["reference_document_id"],
        )
        op.create_index(
            "ix_reference_document_assignments_project",
            "reference_document_assignments",
            ["project_id"],
        )

    if "reference_addition_requests" not in existing:
        op.create_table(
            "reference_addition_requests",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "tenant_id",
                sa.Integer(),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column(
                "requested_by",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("issuing_body", sa.Text(), nullable=True),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("domain_tag", sa.String(length=100), nullable=True),
            sa.Column("justification", sa.Text(), nullable=True),
            sa.Column(
                "status", sa.String(length=20), nullable=False, server_default="pending"
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )

    if "reference_library_import_batches" not in existing:
        op.create_table(
            "reference_library_import_batches",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "tier", sa.String(length=20), nullable=False, server_default="industry"
            ),
            sa.Column(
                "tenant_id",
                sa.Integer(),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column(
                "project_id",
                sa.Integer(),
                sa.ForeignKey("projects.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column(
                "uploaded_by",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "status", sa.String(length=30), nullable=False, server_default="validating"
            ),
            sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("succeeded_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )

    if "reference_library_import_rows" not in existing:
        op.create_table(
            "reference_library_import_rows",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "batch_id",
                sa.Integer(),
                sa.ForeignKey("reference_library_import_batches.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("row_number", sa.Integer(), nullable=False),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("issuing_body", sa.Text(), nullable=True),
            sa.Column("domain_tag", sa.String(length=100), nullable=True),
            sa.Column("applicability_tag", sa.String(length=100), nullable=True),
            sa.Column("source_url", sa.Text(), nullable=False),
            sa.Column("version_label", sa.String(length=255), nullable=True),
            sa.Column("fetch_method_hint", sa.String(length=50), nullable=True),
            sa.Column(
                "status", sa.String(length=20), nullable=False, server_default="pending"
            ),
            sa.Column("failure_reason", sa.Text(), nullable=True),
            sa.Column("warnings", _JSON, nullable=False, server_default="[]"),
            sa.Column("will_update_existing_id", sa.Integer(), nullable=True),
            sa.Column(
                "reference_document_id",
                sa.Integer(),
                sa.ForeignKey("reference_documents.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
        op.create_index(
            "ix_reference_library_import_rows_batch",
            "reference_library_import_rows",
            ["batch_id"],
        )


def downgrade() -> None:
    op.drop_table("reference_library_import_rows")
    op.drop_table("reference_library_import_batches")
    op.drop_table("reference_addition_requests")
    op.drop_table("reference_document_assignments")
    op.drop_table("reference_documents")
