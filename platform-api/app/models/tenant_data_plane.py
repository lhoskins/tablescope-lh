"""Tenant data-plane registry models.

These tables back the multi-tenant on-prem data-access architecture: one shared
EC2 host, one VPC + Site-to-Site VPN per tenant, and one Teiid/WildFly container
per tenant with its own Docker network, VDB directory, secrets and firewall
rules.

``TenantDataPlane`` is the network/runtime isolation record for a customer. It
is intentionally keyed by a string ``tenant_id`` (e.g. ``"acme"``) so it can be
referenced from Terraform outputs, Docker, firewall chains and filesystem paths
without depending on the platform's internal integer tenant id. An optional
``org_tenant_id`` links it to the application-level :class:`~app.models.tenant.Tenant`.

Secrets are never stored here in plaintext — only *references* (e.g. an env var
name or AWS Secrets Manager ARN) live in :class:`TenantSecretRef`.
"""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

# JSONB on Postgres, plain JSON on other dialects (e.g. SQLite used in tests).
_JSON = JSONB().with_variant(JSON(), "sqlite")

DEFAULT_ISOLATION_MODE = "shared_ec2_tenant_vpc_container"
DEFAULT_VDB_CONTAINER_PATH = "/opt/wildfly/teiidfiles/customers"

# Whether this tenant reaches a customer's on-prem network over a dedicated AWS
# Site-to-Site VPN, or runs container-only with no VPN (cloud/SaaS-only data).
VPN_MODE_NONE = "none"
VPN_MODE_CUSTOMER = "customer_vpn"
VPN_MODES = (VPN_MODE_NONE, VPN_MODE_CUSTOMER)
DEFAULT_VPN_MODE = VPN_MODE_NONE


class TenantDataPlane(TimestampMixin, Base):
    __tablename__ = "tenant_data_planes"

    id: Mapped[int] = mapped_column(primary_key=True)

    tenant_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    tenant_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Optional link to the application-level tenant (organization).
    org_tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True
    )

    isolation_mode: Mapped[str] = mapped_column(String(100), nullable=False, default=DEFAULT_ISOLATION_MODE)

    # Tenant tier: 'none' (container-only, no VPN) or 'customer_vpn' (dedicated
    # VPC + Site-to-Site VPN to the customer's on-prem network).
    vpn_mode: Mapped[str] = mapped_column(String(30), nullable=False, default=DEFAULT_VPN_MODE)

    # AWS / network metadata (visible, auditable; no secrets).
    shared_ec2_instance_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    shared_services_vpc_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tenant_vpc_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tenant_subnet_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tenant_route_table_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    customer_gateway_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vpn_connection_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vpn_tunnel1_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vpn_tunnel2_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    routing_type: Mapped[str] = mapped_column(String(20), nullable=False, default="static")
    vpn_status: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Docker / runtime metadata.
    docker_network_name: Mapped[str] = mapped_column(String(255), nullable=False)
    docker_subnet_cidr: Mapped[str] = mapped_column(String(64), nullable=False)
    teiid_container_name: Mapped[str] = mapped_column(String(255), nullable=False)
    teiid_container_ip: Mapped[str] = mapped_column(String(64), nullable=False)
    teiid_servlet_url: Mapped[str] = mapped_column(String(500), nullable=False)
    teiid_pg_host: Mapped[str] = mapped_column(String(255), nullable=False)
    teiid_pg_port: Mapped[int] = mapped_column(Integer, nullable=False)
    teiid_mgmt_port: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Filesystem.
    vdb_host_path: Mapped[str] = mapped_column(String(500), nullable=False)
    vdb_container_path: Mapped[str] = mapped_column(String(500), nullable=False, default=DEFAULT_VDB_CONTAINER_PATH)

    # Network policy.
    allowed_onprem_cidrs: Mapped[list] = mapped_column(_JSON, nullable=False, default=list)
    blocked_cidrs: Mapped[list | None] = mapped_column(_JSON, nullable=True)

    # Lifecycle / health.
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="provisioning")
    last_health_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_health_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    decommission_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("tenant_decommission_jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    secret_refs: Mapped[list[TenantSecretRef]] = relationship(
        back_populates="data_plane",
        cascade="all, delete-orphan",
    )

    def to_dict(self, *, include_network: bool = True) -> dict:
        """Serialize for the admin/API view. Never includes secrets."""
        data: dict = {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "tenant_name": self.tenant_name,
            "org_tenant_id": self.org_tenant_id,
            "isolation_mode": self.isolation_mode,
            "vpn_mode": self.vpn_mode,
            "docker_network_name": self.docker_network_name,
            "docker_subnet_cidr": self.docker_subnet_cidr,
            "teiid_container_name": self.teiid_container_name,
            "teiid_container_ip": self.teiid_container_ip,
            "teiid_servlet_url": self.teiid_servlet_url,
            "teiid_pg_host": self.teiid_pg_host,
            "teiid_pg_port": self.teiid_pg_port,
            "teiid_mgmt_port": self.teiid_mgmt_port,
            "vdb_host_path": self.vdb_host_path,
            "vdb_container_path": self.vdb_container_path,
            "allowed_onprem_cidrs": self.allowed_onprem_cidrs or [],
            "blocked_cidrs": self.blocked_cidrs or [],
            "status": self.status,
            "last_health_status": self.last_health_status,
            "last_health_message": self.last_health_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_network:
            data.update(
                {
                    "shared_ec2_instance_id": self.shared_ec2_instance_id,
                    "shared_services_vpc_id": self.shared_services_vpc_id,
                    "tenant_vpc_id": self.tenant_vpc_id,
                    "tenant_subnet_id": self.tenant_subnet_id,
                    "tenant_route_table_id": self.tenant_route_table_id,
                    "customer_gateway_id": self.customer_gateway_id,
                    "vpn_connection_id": self.vpn_connection_id,
                    "vpn_tunnel1_address": self.vpn_tunnel1_address,
                    "vpn_tunnel2_address": self.vpn_tunnel2_address,
                    "routing_type": self.routing_type,
                    "vpn_status": self.vpn_status,
                }
            )
        return data

    def __repr__(self) -> str:
        return f"TenantDataPlane(id={self.id}, tenant_id={self.tenant_id!r}, " f"status={self.status!r})"


class TenantSecretRef(TimestampMixin, Base):
    __tablename__ = "tenant_secret_refs"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    data_plane_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenant_data_planes.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Logical name of the secret (e.g. "teiid_api_key", "onprem_db_password").
    secret_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # A *reference* to where the secret lives, never the secret itself:
    # e.g. "env:TENANT_ACME_TEIID_API_KEY" or an AWS Secrets Manager ARN.
    secret_ref: Mapped[str] = mapped_column(Text, nullable=False)

    data_plane: Mapped[TenantDataPlane | None] = relationship(back_populates="secret_refs")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "data_plane_id": self.data_plane_id,
            "secret_name": self.secret_name,
            "secret_ref": self.secret_ref,
        }

    def __repr__(self) -> str:
        return f"TenantSecretRef(id={self.id}, tenant_id={self.tenant_id!r}, " f"secret_name={self.secret_name!r})"
