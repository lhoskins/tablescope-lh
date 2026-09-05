"""KG-48: per-stage build metrics.

Adds ``stage_metrics`` to ``knowledge_graph_builds`` -- a per-stage duration
breakdown (queue delay, fingerprinting, source loading, AI enrichment,
validation, activation) plus source counts, so an operator can identify the
slow or failing stage for any build ID without reading raw logs.

Revision ID: 0089
Revises: 0088
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0089"
down_revision: str | None = "0088"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")


def _has_column(conn: sa.engine.Connection, table: str, column: str) -> bool:
    return any(c["name"] == column for c in sa.inspect(conn).get_columns(table))


def upgrade() -> None:
    conn = op.get_bind()
    if _has_column(conn, "knowledge_graph_builds", "stage_metrics"):
        return
    op.add_column(
        "knowledge_graph_builds",
        sa.Column("stage_metrics", _JSON, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("knowledge_graph_builds", "stage_metrics")
