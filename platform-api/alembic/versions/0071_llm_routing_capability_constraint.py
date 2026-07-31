"""Add capability check constraint to llm_routing_profiles.

Revision ID: 0071
Revises: 0070
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0071"
down_revision: Union[str, None] = "0070"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Keep this in sync with app.models.llm_framework.LLMRoutingCapability.
ROUTING_CAPABILITIES = [
    "general_reasoning",
    "sql_generation",
    "insight_interpretation",
    "dashboard_planning",
]

_CAPABILITY_IN_SQL = ", ".join(f"'{c}'" for c in ROUTING_CAPABILITIES)


def upgrade() -> None:
    op.create_check_constraint(
        "ck_llm_routing_profiles_capability",
        "llm_routing_profiles",
        sa.text(f"capability IN ({_CAPABILITY_IN_SQL})"),
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_llm_routing_profiles_capability",
        "llm_routing_profiles",
        type_="check",
    )
