"""Deterministic tenant data-plane layout.

A single source of truth for how a tenant maps onto host resources: its Docker
network/subnet, the Teiid container's fixed IP, the localhost-bound host ports,
and the on-host filesystem paths. The compose generator, firewall generator and
Teiid resolver all derive from these values (which are persisted on the
``tenant_data_planes`` row at creation time), so they can never drift apart.

Port/subnet allocation mirrors the plan's worked example:

    index 1 -> subnet 172.30.10.0/24, teiid ip .10,
               servlet 18095, pg 15442, mgmt 19990
    index 2 -> subnet 172.30.20.0/24, teiid ip .10,
               servlet 28095, pg 25442, mgmt 29990
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

# Base for the per-tenant Docker subnets: 172.30.<10*index>.0/24
DOCKER_SUBNET_SECOND_OCTET = 30
TEIID_CONTAINER_HOST_OCTET = 10  # 172.30.X.10

# Container-internal ports (constant across tenants).
TEIID_SERVLET_CONTAINER_PORT = 8080
TEIID_PG_CONTAINER_PORT = 35432
TEIID_MGMT_CONTAINER_PORT = 9990

# Host port bases (added to index*10000).
HOST_SERVLET_PORT_BASE = 8095
HOST_PG_PORT_BASE = 5442
HOST_MGMT_PORT_BASE = 9990

TENANTS_ROOT = "/opt/tablescope/tenants"

_TENANT_ID_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,48}[a-z0-9])?$")


class InvalidTenantId(ValueError):
    """Raised when a tenant_id is not a safe slug."""


def validate_tenant_id(tenant_id: str) -> str:
    """Validate and normalize a tenant id to a safe lowercase slug.

    The id is used in Docker names, firewall chain names and filesystem paths,
    so it must be a conservative slug (lowercase alphanumeric + hyphen).
    """
    normalized = (tenant_id or "").strip().lower()
    if not _TENANT_ID_RE.match(normalized):
        raise InvalidTenantId(
            "tenant_id must be 1-50 chars, lowercase letters/digits/hyphens, " "and start/end alphanumeric"
        )
    return normalized


@dataclass(frozen=True, slots=True)
class TenantLayout:
    tenant_id: str
    index: int
    docker_network_name: str
    docker_subnet_cidr: str
    teiid_container_name: str
    teiid_container_ip: str
    host_servlet_port: int
    host_pg_port: int
    host_mgmt_port: int
    tenant_root: str
    vdb_host_path: str
    logs_host_path: str
    secrets_host_path: str
    mounts_host_path: str
    compose_host_path: str

    @property
    def teiid_servlet_url(self) -> str:
        """Host-facing servlet URL (when the platform API runs on the host)."""
        return f"http://127.0.0.1:{self.host_servlet_port}"

    @property
    def teiid_pg_host(self) -> str:
        return "127.0.0.1"

    @property
    def teiid_incluster_servlet_url(self) -> str:
        """Servlet URL reachable from a control-plane *container* over the
        tenant Docker network (container IP + container-internal port)."""
        return f"http://{self.teiid_container_ip}:{TEIID_SERVLET_CONTAINER_PORT}"

    @property
    def teiid_incluster_mgmt_url(self) -> str:
        """WildFly management/health URL reachable in-cluster."""
        return f"http://{self.teiid_container_ip}:{TEIID_MGMT_CONTAINER_PORT}"

    @property
    def firewall_chain(self) -> str:
        """Return a short, iptables-safe chain name for this tenant.

        iptables/nftables chain names must be 28 characters or shorter. The
        generated name is deterministic and unique for the tenant id lengths
        supported by :func:`validate_tenant_id`.
        """
        tid = self.tenant_id.upper().replace("-", "_")
        base = f"TS-TENANT-{tid}"
        if len(base) <= 28:
            return base
        short = tid[:18]
        digest = hashlib.md5(tid.encode()).hexdigest()[:6].upper()
        return f"TS-{short}-{digest}"


def compute_layout(tenant_id: str, index: int) -> TenantLayout:
    """Compute the deterministic layout for a tenant given its 1-based index."""
    tid = validate_tenant_id(tenant_id)
    if index < 1 or index > 250:
        raise ValueError("tenant index must be between 1 and 250")

    third_octet = 10 * index
    if third_octet > 250:
        raise ValueError("tenant index too large for the 172.30.0.0/16 subnet plan")

    subnet = f"172.{DOCKER_SUBNET_SECOND_OCTET}.{third_octet}.0/24"
    teiid_ip = f"172.{DOCKER_SUBNET_SECOND_OCTET}.{third_octet}.{TEIID_CONTAINER_HOST_OCTET}"
    root = f"{TENANTS_ROOT}/{tid}"

    return TenantLayout(
        tenant_id=tid,
        index=index,
        docker_network_name=f"tenant_{tid}_net",
        docker_subnet_cidr=subnet,
        teiid_container_name=f"tenant-{tid}-teiid",
        teiid_container_ip=teiid_ip,
        host_servlet_port=index * 10000 + HOST_SERVLET_PORT_BASE,
        host_pg_port=index * 10000 + HOST_PG_PORT_BASE,
        host_mgmt_port=index * 10000 + HOST_MGMT_PORT_BASE,
        tenant_root=root,
        vdb_host_path=f"{root}/vdb",
        logs_host_path=f"{root}/logs",
        secrets_host_path=f"{root}/secrets",
        mounts_host_path=f"{root}/mounts",
        compose_host_path=f"{root}/compose/docker-compose.tenant-{tid}.yml",
    )
