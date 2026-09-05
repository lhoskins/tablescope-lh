"""KG-30: source coverage on knowledge graph health checks.

Adds ``source_coverage`` to ``knowledge_graph_health_checks`` so a health
check report carries per-source-type coverage (matching
``app.services.knowledge_graph_context.coverage.compute_source_coverage``'s
output) alongside structural validity, instead of coverage living only
inside a build version's untyped ``validation_summary`` blob.

Revision ID: 0091
Revises: 0090
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0091"
down_revision: str | None = "0090"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def _has_column(conn: sa.engine.Connection, table: str, column: str) -> bool:
    return any(c["name"] == column for c in sa.inspect(conn).get_columns(table))


def upgrade() -> None:
    conn = op.get_bind()
    if _has_column(conn, "knowledge_graph_health_checks", "source_coverage"):
        return
    op.add_column(
        "knowledge_graph_health_checks",
        sa.Column("source_coverage", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("knowledge_graph_health_checks", "source_coverage")
