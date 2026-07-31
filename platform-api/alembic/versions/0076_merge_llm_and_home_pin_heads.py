"""Merge LLM Framework and home_pin destination heads.

Revision ID: 0076
Revises: 0074, 0075
Create Date: 2026-07-31 00:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0076"
down_revision: str | Sequence[str] | None = ("0074", "0075")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Merge migration: 0074 (LLM Framework) and 0075 (home_pin destination)
    # are independent schema evolutions that both need to be present.
    pass


def downgrade() -> None:
    pass
