"""Fix query_scopes unique constraint to allow multiple targets per source field.

The old constraint UNIQUE(query_id, source_field) only allowed one target per
source field. A column like 'ProductName' may drill down into multiple target
queries — the constraint should be on the full 4-tuple:
(query_id, source_field, target_query_id, target_field).

Revision ID: 0017
Revises: 0016
"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop old constraint if it exists (may not exist on all deployments)
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM pg_constraint WHERE conname = 'uq_query_scopes_query_field'"
    ))
    if result.fetchone():
        op.drop_constraint("uq_query_scopes_query_field", "query_scopes", type_="unique")

    # Create new constraint if it doesn't already exist
    result2 = conn.execute(sa.text(
        "SELECT 1 FROM pg_constraint WHERE conname = 'uq_query_scopes_full'"
    ))
    if not result2.fetchone():
        op.create_unique_constraint(
            "uq_query_scopes_full",
            "query_scopes",
            ["query_id", "source_field", "target_query_id", "target_field"],
        )


def downgrade() -> None:
    op.drop_constraint("uq_query_scopes_full", "query_scopes", type_="unique")
    op.create_unique_constraint(
        "uq_query_scopes_query_field",
        "query_scopes",
        ["query_id", "source_field"],
    )
