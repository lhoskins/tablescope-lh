"""Add live remote file source parameters.

Revision ID: 0082
Revises: 0081
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0082"
down_revision: str | None = "0081"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

_JSONB = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.add_column(
        "file_import_jobs",
        sa.Column("live_source_params", _JSONB, nullable=True),
    )
    op.add_column(
        "file_source_meta",
        sa.Column("live_source_params", _JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("file_source_meta", "live_source_params")
    op.drop_column("file_import_jobs", "live_source_params")
