"""dashboard template groups, bindings and compiled queries

Revision ID: b7e2d8a4c901
Revises: aaa3f7c03dc3
Create Date: 2026-08-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "b7e2d8a4c901"
down_revision: Union[str, None] = "aaa3f7c03dc3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dashboard_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("icon", sa.String(50), nullable=False, server_default="activity"),
        sa.Column("template_id", sa.String(255), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("collapsed_default", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "project_id", "slug", name="uq_dashboard_group_project_slug"),
    )
    op.create_index("ix_dashboard_groups_tenant_id", "dashboard_groups", ["tenant_id"])
    op.create_index("ix_dashboard_groups_project_id", "dashboard_groups", ["project_id"])
    op.create_table(
        "dashboard_template_bindings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dashboard_group_id", sa.Integer(), sa.ForeignKey("dashboard_groups.id", ondelete="SET NULL")),
        sa.Column("template_id", sa.String(255), nullable=False),
        sa.Column("template_name", sa.String(255), nullable=False),
        sa.Column("template_version", sa.String(50), nullable=False, server_default="1"),
        sa.Column("group_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("dimension_config", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("source_mapping", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("field_mapping", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("joins", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("metric_manifest", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("validation", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "project_id", "template_id", "group_key", "version", name="uq_dashboard_template_binding_version"),
    )
    for name, column in (("tenant_id", "tenant_id"), ("project_id", "project_id"), ("dashboard_group_id", "dashboard_group_id"), ("status", "status")):
        op.create_index(f"ix_dashboard_template_bindings_{name}", "dashboard_template_bindings", [column])
    op.create_table(
        "dashboard_template_queries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("binding_id", sa.Integer(), sa.ForeignKey("dashboard_template_bindings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("saved_query_id", sa.Integer(), sa.ForeignKey("saved_queries.id", ondelete="SET NULL")),
        sa.Column("query_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="compiled"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("sql_template", sa.Text(), nullable=False),
        sa.Column("compiled_sql", sa.Text(), nullable=False),
        sa.Column("dashboard_keys", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("metric_keys", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("lineage", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("validation", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("cache_ttl_seconds", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("binding_id", "query_key", "version", name="uq_dashboard_template_query_version"),
    )
    for name in ("tenant_id", "project_id", "binding_id"):
        op.create_index(f"ix_dashboard_template_queries_{name}", "dashboard_template_queries", [name])


def downgrade() -> None:
    op.drop_table("dashboard_template_queries")
    op.drop_table("dashboard_template_bindings")
    op.drop_table("dashboard_groups")
