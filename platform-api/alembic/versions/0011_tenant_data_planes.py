"""Add tenant_data_planes and tenant_secret_refs tables.

Backs the multi-tenant on-prem data-plane architecture: one VPC + Site-to-Site
VPN + Teiid container + Docker network + VDB directory + secrets per tenant on a
single shared EC2 host. Secrets are stored only as references, never plaintext.

Revision ID: 0011_tenant_data_planes
Revises: 0010_database_connections
Create Date: 2026-06-25

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_tenant_data_planes"
down_revision: Union[str, None] = "0010_database_connections"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenant_data_planes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("tenant_name", sa.String(length=255), nullable=False),
        sa.Column(
            "org_tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "isolation_mode",
            sa.String(length=100),
            nullable=False,
            server_default="shared_ec2_tenant_vpc_container",
        ),
        sa.Column("shared_ec2_instance_id", sa.String(length=100), nullable=True),
        sa.Column("shared_services_vpc_id", sa.String(length=100), nullable=True),
        sa.Column("tenant_vpc_id", sa.String(length=100), nullable=True),
        sa.Column("tenant_subnet_id", sa.String(length=100), nullable=True),
        sa.Column("tenant_route_table_id", sa.String(length=100), nullable=True),
        sa.Column("customer_gateway_id", sa.String(length=100), nullable=True),
        sa.Column("vpn_connection_id", sa.String(length=100), nullable=True),
        sa.Column("vpn_tunnel1_address", sa.String(length=64), nullable=True),
        sa.Column("vpn_tunnel2_address", sa.String(length=64), nullable=True),
        sa.Column("routing_type", sa.String(length=20), nullable=False, server_default="static"),
        sa.Column("vpn_status", sa.String(length=50), nullable=True),
        sa.Column("docker_network_name", sa.String(length=255), nullable=False),
        sa.Column("docker_subnet_cidr", sa.String(length=64), nullable=False),
        sa.Column("teiid_container_name", sa.String(length=255), nullable=False),
        sa.Column("teiid_container_ip", sa.String(length=64), nullable=False),
        sa.Column("teiid_servlet_url", sa.String(length=500), nullable=False),
        sa.Column("teiid_pg_host", sa.String(length=255), nullable=False),
        sa.Column("teiid_pg_port", sa.Integer(), nullable=False),
        sa.Column("teiid_mgmt_port", sa.Integer(), nullable=True),
        sa.Column("vdb_host_path", sa.String(length=500), nullable=False),
        sa.Column(
            "vdb_container_path",
            sa.String(length=500),
            nullable=False,
            server_default="/opt/wildfly/teiidfiles/customers",
        ),
        sa.Column(
            "allowed_onprem_cidrs",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("blocked_cidrs", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="provisioning"),
        sa.Column("last_health_status", sa.String(length=50), nullable=True),
        sa.Column("last_health_message", sa.Text(), nullable=True),
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
        "ix_tenant_data_planes_tenant_id",
        "tenant_data_planes",
        ["tenant_id"],
        unique=True,
    )
    op.create_index(
        "ix_tenant_data_planes_org_tenant_id",
        "tenant_data_planes",
        ["org_tenant_id"],
    )

    op.create_table(
        "tenant_secret_refs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column(
            "data_plane_id",
            sa.Integer(),
            sa.ForeignKey("tenant_data_planes.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("secret_name", sa.String(length=255), nullable=False),
        sa.Column("secret_ref", sa.Text(), nullable=False),
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
        "ix_tenant_secret_refs_tenant_id", "tenant_secret_refs", ["tenant_id"]
    )
    op.create_index(
        "ix_tenant_secret_refs_data_plane_id", "tenant_secret_refs", ["data_plane_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_tenant_secret_refs_data_plane_id", table_name="tenant_secret_refs")
    op.drop_index("ix_tenant_secret_refs_tenant_id", table_name="tenant_secret_refs")
    op.drop_table("tenant_secret_refs")
    op.drop_index("ix_tenant_data_planes_org_tenant_id", table_name="tenant_data_planes")
    op.drop_index("ix_tenant_data_planes_tenant_id", table_name="tenant_data_planes")
    op.drop_table("tenant_data_planes")
