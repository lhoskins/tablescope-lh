"""Add query_scopes table (drill-down scopes keyed by saved-query id).

Adds ``query_scopes`` — maps a source saved query + source field to a target
saved query + target field, so a click on a scoped cell drills into the target
query filtered by the clicked value.

Revision ID: 0007_query_scopes
Revises: 0006_saas_connectors
Create Date: 2026-06-01

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_query_scopes"
down_revision: Union[str, None] = "0006_saas_connectors"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "query_scopes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "query_id",
            sa.Integer(),
            sa.ForeignKey("saved_queries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_field", sa.String(length=255), nullable=False),
        sa.Column(
            "target_query_id",
            sa.Integer(),
            sa.ForeignKey("saved_queries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_field", sa.String(length=255), nullable=False),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
    op.create_index("ix_query_scopes_tenant_id", "query_scopes", ["tenant_id"])
    op.create_index("ix_query_scopes_project_id", "query_scopes", ["project_id"])
    op.create_index("ix_query_scopes_query_id", "query_scopes", ["query_id"])
    op.create_unique_constraint(
        "uq_query_scopes_query_field",
        "query_scopes",
        ["query_id", "source_field"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_query_scopes_query_field", "query_scopes", type_="unique"
    )
    op.drop_index("ix_query_scopes_query_id", table_name="query_scopes")
    op.drop_index("ix_query_scopes_project_id", table_name="query_scopes")
    op.drop_index("ix_query_scopes_tenant_id", table_name="query_scopes")
    op.drop_table("query_scopes")
