"""Per-column Teiid type override for database data sources.

Lets users remap a database column's runtime type from the UI (e.g. a column
Teiid imported as ``string`` can be set to ``integer``/``date``).  The override,
when present, takes precedence over the introspected ``data_type`` when the VDB
model is (re)registered.

Revision ID: 0025
Revises: 0024
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def _columns(conn: sa.engine.Connection, table: str) -> set[str]:
    insp = sa.inspect(conn)
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    conn = op.get_bind()
    cols = _columns(conn, "data_source_columns")
    if "teiid_type_override" not in cols:
        op.add_column(
            "data_source_columns",
            sa.Column("teiid_type_override", sa.String(length=50), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("data_source_columns", "teiid_type_override")
