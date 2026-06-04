"""Add source_format to file_source_meta.

JSON/XML uploads are flattened to CSV for the Teiid import pipeline, so the
physical file (and view) becomes ``.csv``. ``source_format`` preserves the
original uploaded extension (e.g. "json", "xml") so the UI can display the
real source type instead of "csv".

Revision ID: 0013_file_source_format
Revises: 0012_tenant_vpn_mode
Create Date: 2026-06-27

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013_file_source_format"
down_revision: Union[str, None] = "0012_tenant_vpn_mode"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "file_source_meta",
        sa.Column("source_format", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("file_source_meta", "source_format")
