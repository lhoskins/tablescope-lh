"""Reference document AI profile — per-document profiling metadata.

Adds a nullable JSON ``ai_metadata`` column to ``reference_documents`` so
company / industry / project reference docs can store the same per-document AI
profile as project documents (document_type, business_domain, tags, kpis,
entities, suggested_questions). No document_family is ever stored here —
families remain project-scoped.

Revision ID: 0048
Revises: 0047
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0048"
down_revision: str | None = "0047"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

_TABLE = "reference_documents"
_COLUMN = "ai_metadata"


def upgrade() -> None:
    conn = op.get_bind()
    existing = {c["name"] for c in sa.inspect(conn).get_columns(_TABLE)}
    if _COLUMN not in existing:
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.JSON(), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    existing = {c["name"] for c in sa.inspect(conn).get_columns(_TABLE)}
    if _COLUMN in existing:
        op.drop_column(_TABLE, _COLUMN)
