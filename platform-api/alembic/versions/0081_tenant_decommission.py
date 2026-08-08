"""tenant decommission

Revision ID: 0081
Revises: 0080
Create Date: 2026-08-06 18:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0081'
down_revision: str | None = '0080'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Tenant decommission job ledger.
    op.create_table(
        "tenant_decommission_jobs",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_pk", sa.Integer(), nullable=True),
        sa.Column("tenant_slug", sa.String(100), nullable=False),
        sa.Column("data_plane_tenant_id", sa.String(100), nullable=True),
        sa.Column("requested_by", sa.Integer(), nullable=False),
        sa.Column("approved_by", sa.Integer(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("current_step", sa.String(50), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("idempotency_key", sa.String(64), nullable=False, unique=True),
        sa.Column("confirmation_phrase", sa.String(100), nullable=False),
        sa.Column("application_sha", sa.String(64), nullable=False),
        sa.Column("infrastructure_sha", sa.String(64), nullable=False),
        sa.Column("terraform_workspace", sa.String(255), nullable=True),
        sa.Column("terraform_state_key", sa.String(500), nullable=True),
        sa.Column("terraform_plan_storage_key", sa.String(500), nullable=True),
        sa.Column("terraform_plan_sha256", sa.String(64), nullable=True),
        sa.Column(
            "terraform_plan_summary",
            postgresql.JSONB().with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
        sa.Column(
            "resource_snapshot",
            postgresql.JSONB().with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
        sa.Column(
            "dependency_snapshot",
            postgresql.JSONB().with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
        sa.Column(
            "verification_results",
            postgresql.JSONB().with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column("error_message_safe", sa.Text(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terraform_applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("aws_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("runtime_cleaned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("data_cleaned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_pk"], ["tenants.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_tenant_decommission_jobs_status", "tenant_decommission_jobs", ["status"]
    )
    op.create_index(
        "ix_tenant_decommission_jobs_tenant_slug_status",
        "tenant_decommission_jobs",
        ["tenant_slug", "status"],
    )

    # Append-only event stream.
    op.create_table(
        "tenant_decommission_events",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("step", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("actor_type", sa.String(50), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=True),
        sa.Column("correlation_id", sa.String(255), nullable=True),
        sa.Column(
            "safe_details",
            postgresql.JSONB().with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"], ["tenant_decommission_jobs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_tenant_decommission_events_job_id",
        "tenant_decommission_events",
        ["job_id"],
    )

    # Tenant lifecycle extension.
    with op.batch_alter_table("tenants") as batch_op:
        batch_op.add_column(
            sa.Column(
                "lifecycle_status",
                sa.String(30),
                nullable=False,
                server_default=sa.text("'active'"),
            )
        )
        batch_op.add_column(
            sa.Column("activity_blocked_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("decommission_job_id", sa.String(36), nullable=True)
        )
        batch_op.add_column(
            sa.Column("decommissioned_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_tenants_decommission_job_id",
            "tenant_decommission_jobs",
            ["decommission_job_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_tenants_decommission_job_id", ["decommission_job_id"], unique=False
        )

    # Data-plane link to decommission job.
    with op.batch_alter_table("tenant_data_planes") as batch_op:
        batch_op.add_column(
            sa.Column("decommission_job_id", sa.String(36), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_tenant_data_planes_decommission_job_id",
            "tenant_decommission_jobs",
            ["decommission_job_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_tenant_data_planes_decommission_job_id",
            ["decommission_job_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("tenant_data_planes") as batch_op:
        batch_op.drop_index("ix_tenant_data_planes_decommission_job_id")
        batch_op.drop_constraint("fk_tenant_data_planes_decommission_job_id", type_="foreignkey")
        batch_op.drop_column("decommission_job_id")

    with op.batch_alter_table("tenants") as batch_op:
        batch_op.drop_index("ix_tenants_decommission_job_id")
        batch_op.drop_constraint("fk_tenants_decommission_job_id", type_="foreignkey")
        batch_op.drop_column("decommissioned_at")
        batch_op.drop_column("decommission_job_id")
        batch_op.drop_column("activity_blocked_at")
        batch_op.drop_column("lifecycle_status")

    op.drop_index("ix_tenant_decommission_events_job_id", "tenant_decommission_events")
    op.drop_table("tenant_decommission_events")
    op.drop_index("ix_tenant_decommission_jobs_tenant_slug_status", "tenant_decommission_jobs")
    op.drop_index("ix_tenant_decommission_jobs_status", "tenant_decommission_jobs")
    op.drop_table("tenant_decommission_jobs")
