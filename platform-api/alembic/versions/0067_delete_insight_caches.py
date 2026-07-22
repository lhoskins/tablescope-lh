"""Delete Business Insight and Project Insight result caches for R-first rebuild.

Revision ID: 0067
Revises: 0066
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0067"
down_revision: str | None = "0066"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM business_insight_results"))
    conn.execute(sa.text("DELETE FROM project_intelligence_snapshots WHERE suite = 'project_insight'"))
    conn.execute(
        sa.text(
            "ALTER SEQUENCE IF EXISTS project_intelligence_snapshots_id_seq RESTART WITH 1"
        )
    )


def downgrade() -> None:
    pass
