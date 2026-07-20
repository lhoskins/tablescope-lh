"""Shared per-project Business Insight result cache.

Revision ID: 0059
Revises: 0058
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0059"
down_revision: str | None = "0058"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")


def _tables(conn: sa.engine.Connection) -> set[str]:
    return set(sa.inspect(conn).get_table_names())


def upgrade() -> None:
    conn = op.get_bind()

    if "business_insight_results" not in _tables(conn):
        op.create_table(
            "business_insight_results",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("granularity", sa.Integer(), nullable=False, server_default="3"),
            sa.Column("kg_version_id", sa.Integer(), nullable=True),
            sa.Column("source_fingerprint", sa.Text(), nullable=True),
            sa.Column("payload", _JSON, nullable=False),
            sa.Column("built_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["kg_version_id"], ["knowledge_graph_versions.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(["built_by"], ["users.id"], ondelete="SET NULL"),
            sa.UniqueConstraint(
                "tenant_id", "project_id", "granularity",
                name="uq_business_insight_result",
            ),
        )
        op.create_index(
            "ix_business_insight_results_tenant_id",
            "business_insight_results",
            ["tenant_id"],
        )
        op.create_index(
            "ix_business_insight_results_project_id",
            "business_insight_results",
            ["project_id"],
        )


def downgrade() -> None:
    conn = op.get_bind()
    if "business_insight_results" in _tables(conn):
        op.drop_table("business_insight_results")
