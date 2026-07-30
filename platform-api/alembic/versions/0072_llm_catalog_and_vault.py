"""Add license approvals and artifact lifecycle constraints for Phase 2.

Revision ID: 0072
Revises: 0071
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0072"
down_revision: Union[str, None] = "0071"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ARTIFACT_STATUSES = [
    "pending",
    "downloading",
    "verifying",
    "staged",
    "verified",
    "quarantined",
    "failed",
]

_LICENSE_STATUS = [
    "pending",
    "review_required",
    "approved",
    "rejected",
]

_ARTIFACT_STATUS_SQL = ", ".join(f"'{s}'" for s in ARTIFACT_STATUSES)
_LICENSE_STATUS_SQL = ", ".join(f"'{s}'" for s in _LICENSE_STATUS)


def upgrade() -> None:
    op.create_table(
        "llm_license_approvals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "artifact_id",
            sa.Integer(),
            sa.ForeignKey("llm_model_artifacts.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
            index=True,
        ),
        sa.Column("license_type", sa.String(255), nullable=True),
        sa.Column("license_url", sa.Text(), nullable=True),
        sa.Column("license_text", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "approved_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            onupdate=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_llm_license_approvals_status",
        "llm_license_approvals",
        sa.text(f"status IN ({_LICENSE_STATUS_SQL})"),
    )

    op.execute(
        sa.text("UPDATE llm_model_artifacts SET publisher = '' WHERE publisher IS NULL")
    )
    op.alter_column(
        "llm_model_artifacts",
        "publisher",
        existing_type=sa.String(255),
        nullable=False,
        server_default="",
    )
    op.create_unique_constraint(
        "uq_llm_model_artifacts_name_publisher_commit_quantization",
        "llm_model_artifacts",
        ["name", "publisher", "commit_sha", "quantization"],
    )
    op.create_check_constraint(
        "ck_llm_model_artifacts_status",
        "llm_model_artifacts",
        sa.text(f"status IN ({_ARTIFACT_STATUS_SQL})"),
    )

    # Track the human requester and the worker/job lifecycle on the artifact.
    op.add_column(
        "llm_model_artifacts",
        sa.Column("requested_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    op.add_column(
        "llm_model_artifacts",
        sa.Column("staged_job_id", sa.String(64), nullable=True, index=True),
    )


def downgrade() -> None:
    op.drop_column("llm_model_artifacts", "staged_job_id")
    op.drop_column("llm_model_artifacts", "requested_by_user_id")
    op.drop_constraint("ck_llm_model_artifacts_status", "llm_model_artifacts", type_="check")
    op.drop_constraint(
        "uq_llm_model_artifacts_name_publisher_commit_quantization",
        "llm_model_artifacts",
        type_="unique",
    )
    op.alter_column(
        "llm_model_artifacts",
        "publisher",
        existing_type=sa.String(255),
        nullable=True,
    )
    op.drop_constraint("ck_llm_license_approvals_status", "llm_license_approvals", type_="check")
    op.drop_table("llm_license_approvals")
