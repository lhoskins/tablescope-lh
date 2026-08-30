"""Shared VDBs: scope to (tenant_id, project_id) instead of tenant_id alone.

``shared_vdbs`` previously had one row per tenant (``uq_shared_vdbs_tenant``),
shared across every project a tenant marks as shared -- confirmed to be the
wrong scope: it let two unrelated shared projects in the same tenant land in
the same physical folder/VDB, and query routing never actually read from it
in the first place (``query_sql_helpers.py`` routed a shared project's
queries to its *owner's private* ``UserVDB`` instead). This migration adds
``project_id`` so a shared project gets its own VDB, matching how the
application code is being changed to create/look one up.

``project_id`` is nullable so the existing (unused, per-tenant) rows are
left in place rather than backfilled or deleted -- they simply won't match
any new lookup, which is the intended fresh start; see the review that
identified this drift for why a backfill isn't attempted here.

Revision ID: 0087
Revises: 0086
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0087"
down_revision = "0086"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "shared_vdbs",
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_shared_vdbs_project_id", "shared_vdbs", ["project_id"]
    )
    op.drop_constraint("uq_shared_vdbs_tenant", "shared_vdbs", type_="unique")
    op.create_unique_constraint(
        "uq_shared_vdbs_tenant_project",
        "shared_vdbs",
        ["tenant_id", "project_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_shared_vdbs_tenant_project", "shared_vdbs", type_="unique"
    )
    # Only safe if every tenant still has at most one shared_vdbs row --
    # true before this migration's rows are created, not guaranteed after.
    op.create_unique_constraint(
        "uq_shared_vdbs_tenant", "shared_vdbs", ["tenant_id"]
    )
    op.drop_index("ix_shared_vdbs_project_id", table_name="shared_vdbs")
    op.drop_column("shared_vdbs", "project_id")
