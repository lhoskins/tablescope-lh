"""Add multi-target runtime, deployment mode, and versioned routing profiles.

Revision ID: 0084
Revises: 652d027cf396
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0084"
down_revision: Union[str, tuple[str, ...], None] = "652d027cf396"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    _JSON = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")

    # --- LLM runtime targets ---
    op.add_column(
        "llm_runtime_targets",
        sa.Column("environment", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "llm_runtime_targets",
        sa.Column("gpu_memory_gb", sa.Integer(), nullable=True),
    )
    op.add_column(
        "llm_runtime_targets",
        sa.Column("system_ram_gb", sa.Integer(), nullable=True),
    )
    op.add_column(
        "llm_runtime_targets",
        sa.Column("disk_gb", sa.Integer(), nullable=True),
    )
    op.add_column(
        "llm_runtime_targets",
        sa.Column("is_internet_isolated", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "llm_runtime_targets",
        sa.Column("max_concurrency", sa.Integer(), nullable=True),
    )
    op.add_column(
        "llm_runtime_targets",
        sa.Column("context_tokens", sa.Integer(), nullable=True),
    )

    # --- LLM installations ---
    op.add_column(
        "llm_installations",
        sa.Column("deployment_mode", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "llm_installations",
        sa.Column("runtime_options", _JSON, nullable=False, server_default="{}"),
    )
    op.create_check_constraint(
        "ck_llm_installations_status",
        "llm_installations",
        sa.text("status IN ('staged', 'installed', 'active', 'rolled_back')"),
    )

    # --- LLM deployments ---
    op.add_column(
        "llm_deployments",
        sa.Column("target_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "llm_deployments",
        sa.Column("deployment_mode", sa.String(length=32), nullable=False, server_default="install_only"),
    )
    op.add_column(
        "llm_deployments",
        sa.Column("runtime_options", _JSON, nullable=False, server_default="{}"),
    )
    op.create_foreign_key(
        "fk_llm_deployments_target_id",
        "llm_deployments",
        "llm_runtime_targets",
        ["target_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_llm_deployments_target_id", "llm_deployments", ["target_id"])
    op.create_check_constraint(
        "ck_llm_deployments_mode",
        "llm_deployments",
        sa.text(
            "deployment_mode IN ('install_only', 'install_and_stage', "
            "'install_and_request_activation', 'replace_active_model')"
        ),
    )
    op.create_check_constraint(
        "ck_llm_deployments_status",
        "llm_deployments",
        sa.text("status IN ('pending', 'approved', 'stabilizing', 'active', 'rolled_back', 'failed')"),
    )

    # --- LLM routing profiles ---
    op.add_column(
        "llm_routing_profiles",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "llm_routing_profiles",
        sa.Column("previous_routing_profile_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "llm_routing_profiles",
        sa.Column("superseded_by_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "llm_routing_profiles",
        sa.Column("deployment_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_llm_routing_profiles_previous_id",
        "llm_routing_profiles",
        "llm_routing_profiles",
        ["previous_routing_profile_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_llm_routing_profiles_superseded_id",
        "llm_routing_profiles",
        "llm_routing_profiles",
        ["superseded_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_llm_routing_profiles_deployment_id",
        "llm_routing_profiles",
        "llm_deployments",
        ["deployment_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_llm_routing_profiles_previous_id", "llm_routing_profiles", ["previous_routing_profile_id"])
    op.create_index("ix_llm_routing_profiles_superseded_id", "llm_routing_profiles", ["superseded_by_id"])
    op.create_index("ix_llm_routing_profiles_deployment_id", "llm_routing_profiles", ["deployment_id"])


def downgrade() -> None:
    # Routing profiles
    op.drop_index("ix_llm_routing_profiles_deployment_id", table_name="llm_routing_profiles")
    op.drop_index("ix_llm_routing_profiles_superseded_id", table_name="llm_routing_profiles")
    op.drop_index("ix_llm_routing_profiles_previous_id", table_name="llm_routing_profiles")
    op.drop_constraint("fk_llm_routing_profiles_deployment_id", "llm_routing_profiles", type_="foreignkey")
    op.drop_constraint("fk_llm_routing_profiles_superseded_id", "llm_routing_profiles", type_="foreignkey")
    op.drop_constraint("fk_llm_routing_profiles_previous_id", "llm_routing_profiles", type_="foreignkey")
    op.drop_column("llm_routing_profiles", "deployment_id")
    op.drop_column("llm_routing_profiles", "superseded_by_id")
    op.drop_column("llm_routing_profiles", "previous_routing_profile_id")
    op.drop_column("llm_routing_profiles", "version")

    # Deployments
    op.drop_constraint("ck_llm_deployments_status", "llm_deployments", type_="check")
    op.drop_constraint("ck_llm_deployments_mode", "llm_deployments", type_="check")
    op.drop_index("ix_llm_deployments_target_id", table_name="llm_deployments")
    op.drop_constraint("fk_llm_deployments_target_id", "llm_deployments", type_="foreignkey")
    op.drop_column("llm_deployments", "runtime_options")
    op.drop_column("llm_deployments", "deployment_mode")
    op.drop_column("llm_deployments", "target_id")

    # Installations
    op.drop_constraint("ck_llm_installations_status", "llm_installations", type_="check")
    op.drop_column("llm_installations", "runtime_options")
    op.drop_column("llm_installations", "deployment_mode")

    # Runtime targets
    op.drop_column("llm_runtime_targets", "context_tokens")
    op.drop_column("llm_runtime_targets", "max_concurrency")
    op.drop_column("llm_runtime_targets", "is_internet_isolated")
    op.drop_column("llm_runtime_targets", "disk_gb")
    op.drop_column("llm_runtime_targets", "system_ram_gb")
    op.drop_column("llm_runtime_targets", "gpu_memory_gb")
    op.drop_column("llm_runtime_targets", "environment")
