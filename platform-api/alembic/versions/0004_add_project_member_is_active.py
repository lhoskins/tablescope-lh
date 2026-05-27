"""Add is_active column to project_members.

Revision ID: 0004_member_active
Revises: 0003_saved_queries
Create Date: 2026-05-28

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_member_active"
down_revision: Union[str, None] = "0003_saved_queries"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "project_members",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("project_members", "is_active")
