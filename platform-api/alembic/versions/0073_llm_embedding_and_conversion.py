"""Add Phase 5 embedding re-index migrations and Phase 6 FP16 conversion tables.

Revision ID: 0073
Revises: 0072
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0073"
down_revision: Union[str, None] = "0072"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_EMIStatuses = [
    "pending",
    "creating_target",
    "reindexing",
    "comparing",
    "completed",
    "failed",
    "rolled_back",
]

_CONVERSION_STATUSES = [
    "pending",
    "downloading",
    "converting",
    "verifying",
    "completed",
    "failed",
]

_FORMATS = ["gguf", "safetensors", "pytorch", "fp16", "unknown"]


def upgrade() -> None:
    # Allow non-GGUF source artifacts for the FP16 -> GGUF conversion pipeline.
    # The older single-format constraint may not exist in all environments, so
    # drop it idempotently on PostgreSQL before adding the new one.
    if op.get_context().dialect.name == "postgresql":
        op.execute("ALTER TABLE llm_model_artifacts DROP CONSTRAINT IF EXISTS ck_llm_model_artifacts_format_gguf")
    op.create_check_constraint(
        "ck_llm_model_artifacts_format",
        "llm_model_artifacts",
        sa.text(f"format IN ({', '.join(repr(f) for f in _FORMATS)})")
    )

    op.add_column(
        "llm_model_artifacts",
        sa.Column("embedding_dim", sa.Integer(), nullable=True),
    )

    op.create_table(
        "llm_embedding_migrations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "artifact_id",
            sa.Integer(),
            sa.ForeignKey("llm_model_artifacts.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("source_collection", sa.String(255), nullable=False),
        sa.Column("target_collection", sa.String(255), nullable=False),
        sa.Column("embedding_model", sa.String(255), nullable=False),
        sa.Column("embedding_dim", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("recall_score", sa.Float(), nullable=True),
        sa.Column("points_total", sa.Integer(), nullable=True),
        sa.Column("points_indexed", sa.Integer(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
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
        "ck_llm_embedding_migrations_status",
        "llm_embedding_migrations",
        sa.text(f"status IN ({', '.join(repr(s) for s in _EMIStatuses)})")
    )

    op.create_table(
        "llm_model_conversions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "source_artifact_id",
            sa.Integer(),
            sa.ForeignKey("llm_model_artifacts.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "output_artifact_id",
            sa.Integer(),
            sa.ForeignKey("llm_model_artifacts.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("quantization", sa.String(32), nullable=True),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("converter_version", sa.String(255), nullable=True),
        sa.Column("converter_command", sa.Text(), nullable=True),
        sa.Column("output_manifest", sa.JSON(), nullable=True),
        sa.Column("output_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
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
        "ck_llm_model_conversions_status",
        "llm_model_conversions",
        sa.text(f"status IN ({', '.join(repr(s) for s in _CONVERSION_STATUSES)})")
    )


def downgrade() -> None:
    op.drop_table("llm_model_conversions")
    op.drop_table("llm_embedding_migrations")
    op.drop_column("llm_model_artifacts", "embedding_dim")
    op.drop_constraint("ck_llm_model_artifacts_format", "llm_model_artifacts", type_="check")
    op.create_check_constraint(
        "ck_llm_model_artifacts_format_gguf",
        "llm_model_artifacts",
        sa.text("format = 'gguf'"),
    )
