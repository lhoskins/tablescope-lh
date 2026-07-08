"""Analytical Method Reference Catalog — governed statistical-method registry.

Adds the six tables backing the Analytical Method Engine's governed catalog:
method_catalogs, method_catalog_versions, analytical_methods,
analytical_shared_policies, method_selection_matrix, method_catalog_audit_log.

Idempotent: each table is created only if it does not already exist.

Revision ID: 0048
Revises: 0047
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

from alembic import op

revision: str = "0048"
down_revision: str | None = "0047"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

_JSON = JSONB().with_variant(JSON(), "sqlite")


def _has_table(conn, name: str) -> bool:
    return name in sa.inspect(conn).get_table_names()


def upgrade() -> None:
    conn = op.get_bind()

    if not _has_table(conn, "method_catalogs"):
        op.create_table(
            "method_catalogs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("catalog_key", sa.String(length=100), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text()),
            sa.Column("source_document", sa.String(length=255)),
            sa.Column("is_system", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column("active_version_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("catalog_key"),
        )

    if not _has_table(conn, "method_catalog_versions"):
        op.create_table(
            "method_catalog_versions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "catalog_id",
                sa.Integer(),
                sa.ForeignKey("method_catalogs.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("version", sa.String(length=50), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="draft"),
            sa.Column("notes", sa.Text()),
            sa.Column("method_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("catalog_id", "version"),
        )

    if not _has_table(conn, "analytical_methods"):
        op.create_table(
            "analytical_methods",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "catalog_version_id",
                sa.Integer(),
                sa.ForeignKey("method_catalog_versions.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("method_id", sa.String(length=150), nullable=False),
            sa.Column("display_name", sa.String(length=255), nullable=False),
            sa.Column("category", sa.String(length=150)),
            sa.Column("subcategory", sa.String(length=150)),
            sa.Column("tier", sa.Integer(), nullable=False, server_default="2"),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="draft"),
            sa.Column("summary", sa.Text()),
            sa.Column("applicability_condition", sa.Text()),
            sa.Column("supported_intents", _JSON, nullable=False, server_default="[]"),
            sa.Column("selection_rules", _JSON, nullable=False, server_default="[]"),
            sa.Column("rejection_rules", _JSON, nullable=False, server_default="[]"),
            sa.Column("required_checks", _JSON, nullable=False, server_default="[]"),
            sa.Column("fallback_methods", _JSON, nullable=False, server_default="[]"),
            sa.Column("output_contract", _JSON, nullable=False, server_default="{}"),
            sa.Column("method_card", _JSON, nullable=False, server_default="{}"),
            sa.Column("llm_guardrails", _JSON, nullable=False, server_default="[]"),
            sa.Column("executor_key", sa.String(length=150), nullable=True),
            sa.Column("dependencies", _JSON, nullable=False, server_default="[]"),
            sa.Column("is_executable", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("catalog_version_id", "method_id"),
        )

    if not _has_table(conn, "analytical_shared_policies"):
        op.create_table(
            "analytical_shared_policies",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "catalog_version_id",
                sa.Integer(),
                sa.ForeignKey("method_catalog_versions.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("policy_key", sa.String(length=100), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text()),
            sa.Column("rules", _JSON, nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("catalog_version_id", "policy_key"),
        )

    if not _has_table(conn, "method_selection_matrix"):
        op.create_table(
            "method_selection_matrix",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "catalog_version_id",
                sa.Integer(),
                sa.ForeignKey("method_catalog_versions.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("analysis_intent", sa.String(length=100), nullable=False),
            sa.Column("data_profile", sa.String(length=255)),
            sa.Column("primary_method_id", sa.String(length=150), nullable=False),
            sa.Column("alternative_method_ids", _JSON, nullable=False, server_default="[]"),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if not _has_table(conn, "method_catalog_audit_log"):
        op.create_table(
            "method_catalog_audit_log",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "tenant_id",
                sa.Integer(),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("catalog_version_id", sa.Integer(), nullable=True),
            sa.Column("method_id", sa.String(length=150), nullable=True),
            sa.Column("event_type", sa.String(length=50), nullable=False),
            sa.Column("analysis_intent", sa.String(length=100)),
            sa.Column("selected_method", sa.String(length=150)),
            sa.Column("rejected_methods", _JSON, nullable=False, server_default="[]"),
            sa.Column("envelope", _JSON, nullable=True),
            sa.Column("reason", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )


def downgrade() -> None:
    for table in (
        "method_catalog_audit_log",
        "method_selection_matrix",
        "analytical_shared_policies",
        "analytical_methods",
        "method_catalog_versions",
        "method_catalogs",
    ):
        op.drop_table(table)
