"""Project Insight acknowledgement — snapshot columns for the Reviewed list.

Adds title/summary/category/severity so a reviewed insight can be listed and
reopened later even after the AI report is regenerated with different items.

Revision ID: 0046
Revises: 0045
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0046"
down_revision: str | None = "0045"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

_TABLE = "project_insight_acknowledgements"
_COLUMNS = (
    ("title", sa.String(length=500)),
    ("summary", sa.Text()),
    ("category", sa.String(length=100)),
    ("severity", sa.String(length=50)),
)


def upgrade() -> None:
    conn = op.get_bind()
    existing = {c["name"] for c in sa.inspect(conn).get_columns(_TABLE)}
    for name, type_ in _COLUMNS:
        if name not in existing:
            op.add_column(_TABLE, sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    existing = {c["name"] for c in sa.inspect(conn).get_columns(_TABLE)}
    for name, _type in reversed(_COLUMNS):
        if name in existing:
            op.drop_column(_TABLE, name)
