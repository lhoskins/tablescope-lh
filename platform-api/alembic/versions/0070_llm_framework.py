"""Add LLM Framework inventory and deployment tables.

Revision ID: 0070
Revises: 0069
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0070"
down_revision: str | None = "0069"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # Runtime targets: Ollama hosts where models can be installed.
    op.create_table(
        "llm_runtime_targets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("runtime_type", sa.String(32), nullable=False, server_default="ollama"),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("version", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("is_reachable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_loaded_models", sa.Integer(), nullable=True),
        sa.Column("keep_alive_minutes", sa.Integer(), nullable=True),
        sa.Column("labels", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Model artifacts: verified (or quarantined) GGUF packages staged in the vault.
    op.create_table(
        "llm_model_artifacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("publisher", sa.String(255), nullable=True),
        sa.Column("repo_url", sa.Text(), nullable=True),
        sa.Column("commit_sha", sa.String(64), nullable=True),
        sa.Column("quantization", sa.String(32), nullable=True),
        sa.Column("format", sa.String(32), nullable=False, server_default="gguf"),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("manifest", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("manifest_signature", sa.Text(), nullable=True),
        sa.Column("manifest_public_key_fingerprint", sa.String(128), nullable=True),
        sa.Column("quarantine_reason", sa.Text(), nullable=True),
        sa.Column("verified_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Individual files belonging to an artifact, with their verification hashes.
    op.create_table(
        "llm_artifact_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "artifact_id",
            sa.Integer(),
            sa.ForeignKey("llm_model_artifacts.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("hash_algorithm", sa.String(32), nullable=False, server_default="sha256"),
        sa.Column("hash_value", sa.String(128), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Installations of an artifact on a runtime target.
    op.create_table(
        "llm_installations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "artifact_id",
            sa.Integer(),
            sa.ForeignKey("llm_model_artifacts.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "target_id",
            sa.Integer(),
            sa.ForeignKey("llm_runtime_targets.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="staged"),
        sa.Column("installed_path", sa.Text(), nullable=True),
        sa.Column("modelfile_content", sa.Text(), nullable=True),
        sa.Column("installed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "previous_installation_id",
            sa.Integer(),
            sa.ForeignKey("llm_installations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Routing profiles: map a capability to an installation on a target.
    op.create_table(
        "llm_routing_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("capability", sa.String(64), nullable=False, index=True),
        sa.Column(
            "target_id",
            sa.Integer(),
            sa.ForeignKey("llm_runtime_targets.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "installation_id",
            sa.Integer(),
            sa.ForeignKey("llm_installations.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("priority", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("config", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Deployments: a request to promote an installation to active routing.
    op.create_table(
        "llm_deployments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "installation_id",
            sa.Integer(),
            sa.ForeignKey("llm_installations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "requested_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "approved_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column(
            "previous_deployment_id",
            sa.Integer(),
            sa.ForeignKey("llm_deployments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("stabilization_window_seconds", sa.Integer(), nullable=True),
        sa.Column("stabilized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Deployment attempts: granular log of each deployment step.
    op.create_table(
        "llm_deployment_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "deployment_id",
            sa.Integer(),
            sa.ForeignKey("llm_deployments.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Platform-scoped audit events for LLM framework actions. Existing
    # audit_events requires a tenant_id, which is wrong for platform infra.
    op.create_table(
        "llm_audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(100), nullable=False, index=True),
        sa.Column("entity_type", sa.String(64), nullable=True, index=True),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("llm_audit_events")
    op.drop_table("llm_deployment_attempts")
    op.drop_table("llm_deployments")
    op.drop_table("llm_routing_profiles")
    op.drop_table("llm_installations")
    op.drop_table("llm_artifact_files")
    op.drop_table("llm_model_artifacts")
    op.drop_table("llm_runtime_targets")
