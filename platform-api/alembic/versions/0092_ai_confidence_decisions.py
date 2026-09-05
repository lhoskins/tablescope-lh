"""KG-32: durable capture of AI confidence vs. the human decision made on it.

Adds ``ai_confidence_decisions``, one row per human accept/change/remove
decision on an AI-suggested Knowledge Graph edge (document-family curation
today). Previously this pair only ever reached ``log_family_event`` -- a log
line, not a queryable table -- and the model's own confidence at the moment
of the decision was discarded once the decision was applied. Groundwork only:
this does not itself compute any calibration curve.

Revision ID: 0092
Revises: 0091
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0092"
down_revision: str | None = "0091"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_confidence_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "project_id", sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "asset_id", sa.Integer(),
            sa.ForeignKey("project_assets.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("source_pipeline", sa.String(length=50), nullable=False),
        sa.Column("ai_confidence_at_decision", sa.Float(), nullable=True),
        sa.Column("human_decision", sa.String(length=20), nullable=False),
        sa.Column(
            "decided_by", sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "decided_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_ai_confidence_decisions_tenant_id", "ai_confidence_decisions", ["tenant_id"],
    )
    op.create_index(
        "ix_ai_confidence_decisions_project_id", "ai_confidence_decisions", ["project_id"],
    )
    op.create_index(
        "ix_ai_confidence_decisions_asset_id", "ai_confidence_decisions", ["asset_id"],
    )
    op.create_index(
        "ix_ai_confidence_decisions_source_pipeline",
        "ai_confidence_decisions", ["source_pipeline"],
    )
    op.create_index(
        "ix_ai_confidence_decisions_human_decision",
        "ai_confidence_decisions", ["human_decision"],
    )


def downgrade() -> None:
    op.drop_table("ai_confidence_decisions")
