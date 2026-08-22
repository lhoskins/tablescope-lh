"""dashboard primary dimensions

Revision ID: c4d92a811e01
Revises: b7e2d8a4c901
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4d92a811e01"
down_revision: str | None = "b7e2d8a4c901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dashboard_primary_dimensions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_view", sa.String(255), nullable=False),
        sa.Column("field", sa.String(255), nullable=False),
        sa.Column("default_label", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "tenant_id", "project_id", "source_view", "field",
            name="uq_dashboard_primary_dimension_field",
        ),
    )
    for name in ("tenant_id", "project_id"):
        op.create_index(f"ix_dashboard_primary_dimensions_{name}", "dashboard_primary_dimensions", [name])

    op.create_table(
        "dashboard_primary_dimension_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dashboard_id", sa.Integer(), sa.ForeignKey("dashboards.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "dimension_id", sa.Integer(),
            sa.ForeignKey("dashboard_primary_dimensions.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "dashboard_id", "dimension_id", name="uq_dashboard_primary_dimension_assignment",
        ),
    )
    for name in ("tenant_id", "project_id", "dashboard_id", "dimension_id"):
        op.create_index(
            f"ix_dashboard_primary_dimension_assignments_{name}",
            "dashboard_primary_dimension_assignments", [name],
        )

    op.create_table(
        "dashboard_primary_dimension_bindings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "assignment_id", sa.Integer(),
            sa.ForeignKey("dashboard_primary_dimension_assignments.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("widget_id", sa.String(255), nullable=False),
        sa.Column("column_name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "assignment_id", "widget_id", name="uq_dashboard_primary_dimension_binding_widget",
        ),
    )
    for name in ("tenant_id", "project_id", "assignment_id"):
        op.create_index(
            f"ix_dashboard_primary_dimension_bindings_{name}",
            "dashboard_primary_dimension_bindings", [name],
        )


def downgrade() -> None:
    op.drop_table("dashboard_primary_dimension_bindings")
    op.drop_table("dashboard_primary_dimension_assignments")
    op.drop_table("dashboard_primary_dimensions")
