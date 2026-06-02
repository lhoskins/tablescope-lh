"""Add grid_preferences table and archive columns on database_data_sources.

- ``grid_preferences``: per-user column order + hidden columns for a saved
  query's result grid (item: MUI X persisted column layout).
- ``database_data_sources.archived`` / ``archived_at``: soft-archive a data
  source so it is hidden from the active list but may still be deleted once no
  active query depends on it (item: archive data source).

Revision ID: 0008_grid_prefs_archive
Revises: 0007_query_scopes
Create Date: 2026-06-15

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_grid_prefs_archive"
down_revision: Union[str, None] = "0007_query_scopes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "grid_preferences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "query_id",
            sa.Integer(),
            sa.ForeignKey("saved_queries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("column_order", postgresql.JSONB(), nullable=True),
        sa.Column("hidden_columns", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_grid_preferences_tenant_id", "grid_preferences", ["tenant_id"]
    )
    op.create_index("ix_grid_preferences_user_id", "grid_preferences", ["user_id"])
    op.create_index("ix_grid_preferences_query_id", "grid_preferences", ["query_id"])
    op.create_unique_constraint(
        "uq_grid_pref_user_query", "grid_preferences", ["user_id", "query_id"]
    )

    op.add_column(
        "database_data_sources",
        sa.Column(
            "archived",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "database_data_sources",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("database_data_sources", "archived_at")
    op.drop_column("database_data_sources", "archived")
    op.drop_constraint(
        "uq_grid_pref_user_query", "grid_preferences", type_="unique"
    )
    op.drop_index("ix_grid_preferences_query_id", table_name="grid_preferences")
    op.drop_index("ix_grid_preferences_user_id", table_name="grid_preferences")
    op.drop_index("ix_grid_preferences_tenant_id", table_name="grid_preferences")
    op.drop_table("grid_preferences")
