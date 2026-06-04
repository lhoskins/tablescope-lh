"""Add vpn_mode to tenant_data_planes.

Tenant tier selector: 'none' (container-only, no VPN) vs 'customer_vpn'
(dedicated VPC + Site-to-Site VPN to the customer's on-prem network). Backfills
existing rows that already carry VPN metadata to 'customer_vpn'.

Revision ID: 0012_tenant_vpn_mode
Revises: 0011_tenant_data_planes
Create Date: 2026-06-26

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012_tenant_vpn_mode"
down_revision: Union[str, None] = "0011_tenant_data_planes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tenant_data_planes",
        sa.Column(
            "vpn_mode",
            sa.String(length=30),
            nullable=False,
            server_default="none",
        ),
    )
    # Existing tenants that already have VPN metadata are customer_vpn tier.
    op.execute(
        "UPDATE tenant_data_planes SET vpn_mode = 'customer_vpn' "
        "WHERE vpn_connection_id IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("tenant_data_planes", "vpn_mode")
