"""Knowledge Graph snapshots: persist the latest full project graph.

Adds:
- ``ai_project_graph_snapshots`` — one row per (tenant, project, snapshot_key);
  caches the full merged Knowledge Graph so node clicks recenter/filter from the
  cached nodes/edges and only a manual Refresh rebuilds it (mirrors AI Home).

Revision ID: 0034
Revises: 0033
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")


def _tables(conn: sa.engine.Connection) -> set[str]:
    return set(sa.inspect(conn).get_table_names())


def upgrade() -> None:
    conn = op.get_bind()
    if "ai_project_graph_snapshots" in _tables(conn):
        return
    op.create_table(
        "ai_project_graph_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_key", sa.String(length=120), nullable=False),
        sa.Column("payload", _JSON, nullable=False, server_default="{}"),
        sa.Column("pipeline_version", sa.String(length=120), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "uq_ai_project_graph_snapshot_project",
        "ai_project_graph_snapshots",
        ["tenant_id", "project_id", "snapshot_key"],
        unique=True,
    )
    op.create_index(
        "ix_ai_project_graph_snapshots_generated_at",
        "ai_project_graph_snapshots",
        ["tenant_id", "project_id", "generated_at"],
    )


def downgrade() -> None:
    op.drop_table("ai_project_graph_snapshots")
