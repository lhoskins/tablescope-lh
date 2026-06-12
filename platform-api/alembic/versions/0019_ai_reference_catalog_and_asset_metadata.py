"""AI reference catalog, asset tags, and asset KPIs.

Revision ID: 0019
Revises: 0018
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    conn = op.get_bind()

    # ── Reference catalogs ────────────────────────────────────────────────
    if not _table_exists(conn, "ai_reference_catalogs"):
        op.create_table(
            "ai_reference_catalogs",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("catalog_key", sa.String(100), nullable=False, unique=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text),
            sa.Column("industry", sa.String(100)),
            sa.Column("source_framework", sa.String(255)),
            sa.Column("version", sa.String(50), nullable=False, server_default="1.0"),
            sa.Column("is_system", sa.Boolean, nullable=False, server_default="true"),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    # ── Reference tags ────────────────────────────────────────────────────
    if not _table_exists(conn, "ai_reference_tags"):
        op.create_table(
            "ai_reference_tags",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("catalog_id", sa.Integer, sa.ForeignKey("ai_reference_catalogs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("tag_key", sa.String(150), nullable=False),
            sa.Column("display_name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text),
            sa.Column("industry", sa.String(100)),
            sa.Column("business_domain", sa.String(100)),
            sa.Column("process_area", sa.String(100)),
            sa.Column("synonyms", JSONB, nullable=False, server_default="[]"),
            sa.Column("related_tags", JSONB, nullable=False, server_default="[]"),
            sa.Column("example_fields", JSONB, nullable=False, server_default="[]"),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("catalog_id", "tag_key"),
        )

    # ── Reference KPIs ────────────────────────────────────────────────────
    if not _table_exists(conn, "ai_reference_kpis"):
        op.create_table(
            "ai_reference_kpis",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("catalog_id", sa.Integer, sa.ForeignKey("ai_reference_catalogs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("kpi_key", sa.String(150), nullable=False),
            sa.Column("display_name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text),
            sa.Column("industry", sa.String(100)),
            sa.Column("business_domain", sa.String(100)),
            sa.Column("process_area", sa.String(100)),
            sa.Column("formula", sa.Text),
            sa.Column("required_fields", JSONB, nullable=False, server_default="[]"),
            sa.Column("optional_fields", JSONB, nullable=False, server_default="[]"),
            sa.Column("related_tags", JSONB, nullable=False, server_default="[]"),
            sa.Column("recommended_chart_type", sa.String(50)),
            sa.Column("recommended_aggregations", JSONB, nullable=False, server_default="[]"),
            sa.Column("example_sql_template", sa.Text),
            sa.Column("benchmark_source", sa.String(255)),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("catalog_id", "kpi_key"),
        )

    # ── Tenant catalog enablement ─────────────────────────────────────────
    if not _table_exists(conn, "tenant_reference_catalogs"):
        op.create_table(
            "tenant_reference_catalogs",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("catalog_id", sa.Integer, sa.ForeignKey("ai_reference_catalogs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("is_enabled", sa.Boolean, nullable=False, server_default="true"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("tenant_id", "catalog_id"),
        )

    # ── Tenant custom tags ────────────────────────────────────────────────
    if not _table_exists(conn, "tenant_custom_tags"):
        op.create_table(
            "tenant_custom_tags",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("tag_key", sa.String(150), nullable=False),
            sa.Column("display_name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text),
            sa.Column("industry", sa.String(100)),
            sa.Column("business_domain", sa.String(100)),
            sa.Column("process_area", sa.String(100)),
            sa.Column("synonyms", JSONB, nullable=False, server_default="[]"),
            sa.Column("related_tags", JSONB, nullable=False, server_default="[]"),
            sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("tenant_id", "tag_key"),
        )

    # ── Tenant custom KPIs ────────────────────────────────────────────────
    if not _table_exists(conn, "tenant_custom_kpis"):
        op.create_table(
            "tenant_custom_kpis",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("kpi_key", sa.String(150), nullable=False),
            sa.Column("display_name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text),
            sa.Column("business_domain", sa.String(100)),
            sa.Column("process_area", sa.String(100)),
            sa.Column("formula", sa.Text),
            sa.Column("required_fields", JSONB, nullable=False, server_default="[]"),
            sa.Column("optional_fields", JSONB, nullable=False, server_default="[]"),
            sa.Column("related_tags", JSONB, nullable=False, server_default="[]"),
            sa.Column("recommended_chart_type", sa.String(50)),
            sa.Column("recommended_aggregations", JSONB, nullable=False, server_default="[]"),
            sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("tenant_id", "kpi_key"),
        )

    # ── Asset tag suggestions ─────────────────────────────────────────────
    if not _table_exists(conn, "ai_asset_tag_suggestions"):
        op.create_table(
            "ai_asset_tag_suggestions",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("source_type", sa.String(100), nullable=False),
            sa.Column("source_id", sa.Integer, nullable=False),
            sa.Column("tag_key", sa.String(150), nullable=False),
            sa.Column("display_name", sa.String(255), nullable=False),
            sa.Column("confidence", sa.Numeric(5, 4)),
            sa.Column("reason", sa.Text),
            sa.Column("status", sa.String(50), nullable=False, server_default="suggested"),
            sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    # ── Accepted asset tags ───────────────────────────────────────────────
    if not _table_exists(conn, "ai_asset_tags"):
        op.create_table(
            "ai_asset_tags",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("source_type", sa.String(100), nullable=False),
            sa.Column("source_id", sa.Integer, nullable=False),
            sa.Column("tag_key", sa.String(150), nullable=False),
            sa.Column("display_name", sa.String(255), nullable=False),
            sa.Column("business_domain", sa.String(100)),
            sa.Column("process_area", sa.String(100)),
            sa.Column("confidence", sa.Numeric(5, 4)),
            sa.Column("source", sa.String(50), nullable=False, server_default="ai_suggested"),
            sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("tenant_id", "project_id", "source_type", "source_id", "tag_key"),
        )

    # ── Asset KPI suggestions ─────────────────────────────────────────────
    if not _table_exists(conn, "ai_asset_kpi_suggestions"):
        op.create_table(
            "ai_asset_kpi_suggestions",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("source_type", sa.String(100), nullable=False),
            sa.Column("source_id", sa.Integer, nullable=False),
            sa.Column("kpi_key", sa.String(150), nullable=False),
            sa.Column("display_name", sa.String(255), nullable=False),
            sa.Column("confidence", sa.Numeric(5, 4)),
            sa.Column("field_mapping", JSONB, nullable=False, server_default="{}"),
            sa.Column("formula", sa.Text),
            sa.Column("recommended_chart_type", sa.String(50)),
            sa.Column("reason", sa.Text),
            sa.Column("status", sa.String(50), nullable=False, server_default="suggested"),
            sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    # ── Accepted asset KPIs ───────────────────────────────────────────────
    if not _table_exists(conn, "ai_asset_kpis"):
        op.create_table(
            "ai_asset_kpis",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("source_type", sa.String(100), nullable=False),
            sa.Column("source_id", sa.Integer, nullable=False),
            sa.Column("kpi_key", sa.String(150), nullable=False),
            sa.Column("display_name", sa.String(255), nullable=False),
            sa.Column("field_mapping", JSONB, nullable=False, server_default="{}"),
            sa.Column("formula", sa.Text),
            sa.Column("recommended_chart_type", sa.String(50)),
            sa.Column("confidence", sa.Numeric(5, 4)),
            sa.Column("source", sa.String(50), nullable=False, server_default="ai_suggested"),
            sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("tenant_id", "project_id", "source_type", "source_id", "kpi_key"),
        )

    # ── Add ai_metadata columns to file_source_meta ───────────────────────
    if not _column_exists(conn, "file_source_meta", "ai_metadata"):
        op.add_column("file_source_meta", sa.Column("ai_metadata", JSONB, nullable=False, server_default="{}"))
    if not _column_exists(conn, "file_source_meta", "ai_profile_status"):
        op.add_column("file_source_meta", sa.Column("ai_profile_status", sa.String(50), nullable=False, server_default="pending"))
    if not _column_exists(conn, "file_source_meta", "ai_profiled_at"):
        op.add_column("file_source_meta", sa.Column("ai_profiled_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("file_source_meta", "ai_profiled_at")
    op.drop_column("file_source_meta", "ai_profile_status")
    op.drop_column("file_source_meta", "ai_metadata")
    for t in (
        "ai_asset_kpis",
        "ai_asset_kpi_suggestions",
        "ai_asset_tags",
        "ai_asset_tag_suggestions",
        "tenant_custom_kpis",
        "tenant_custom_tags",
        "tenant_reference_catalogs",
        "ai_reference_kpis",
        "ai_reference_tags",
        "ai_reference_catalogs",
    ):
        op.drop_table(t)


def _table_exists(conn, name: str) -> bool:
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = :t"),
        {"t": name},
    )
    return result.fetchone() is not None


def _column_exists(conn, table: str, column: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    )
    return result.fetchone() is not None
