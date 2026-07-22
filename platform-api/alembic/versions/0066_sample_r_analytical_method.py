"""Neutralized: sample R-backed analytical method is now seeded via catalog.

Revision ID: 0066
Revises: 0065
"""

from __future__ import annotations

revision: str = "0066"
down_revision: str | None = "0065"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    """No-op. The r_descriptive_profile replacement (describe_numeric) is now
    emitted by the seed catalog with execution_engine='r'."""
    pass


def downgrade() -> None:
    pass
