"""AI conversation message result data — structured executed-query payload.

Adds a nullable JSON ``data`` column so an assistant message can carry the
executed query result (sql, columns, rows, suggested visualization) it was
grounded on, letting the AI Assistant render answers like the Project Insight
page instead of only plain text.

Revision ID: 0047
Revises: 0046
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0047"
down_revision: str | None = "0046"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

_TABLE = "ai_conversation_messages"
_COLUMN = "data"


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
