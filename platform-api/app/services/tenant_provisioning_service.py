"""Orchestrate tenant data-plane provisioning in the registry.

This is the control-plane glue: it allocates a deterministic layout for a new
tenant, persists a :class:`TenantDataPlane` row (plus secret *references*),
and can import Terraform VPN/VPC outputs onto an existing tenant. It also
renders (but does not apply) the tenant compose file and host firewall script.

It deliberately does not start containers or touch iptables itself — those
require host/root access and are performed by an operator or privileged worker
using the rendered artifacts. The API stays least-privilege.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant_data_plane import (
    DEFAULT_ISOLATION_MODE,
    TenantDataPlane,
    TenantSecretRef,
)
from app.services.tenant_compose_service import TenantComposeService
from app.services.tenant_firewall_service import (
    TenantFirewallService,
    TenantFirewallSpec,
)
from app.services.tenant_layout import TenantLayout, compute_layout, validate_tenant_id


class TenantAlreadyExists(Exception):
    pass


class TenantNotFound(Exception):
    pass


@dataclass(slots=True)
class VpnMetadata:
    tenant_vpc_id: str | None = None
    tenant_subnet_id: str | None = None
    tenant_route_table_id: str | None = None
    customer_gateway_id: str | None = None
    vpn_connection_id: str | None = None
    vpn_tunnel1_address: str | None = None
    vpn_tunnel2_address: str | None = None
    shared_services_vpc_id: str | None = None
    shared_ec2_instance_id: str | None = None
    routing_type: str | None = None


class TenantProvisioningService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _existing_indexes(self) -> set[int]:
        rows = (await self._session.scalars(select(TenantDataPlane.docker_subnet_cidr))).all()
        indexes: set[int] = set()
        for cidr in rows:
            # 172.30.<10*index>.0/24
            try:
                third = int(cidr.split(".")[2])
                indexes.add(third // 10)
            except (ValueError, IndexError):
                continue
        return indexes

    async def _next_index(self) -> int:
        used = await self._existing_indexes()
        idx = 1
        while idx in used:
            idx += 1
        return idx

    async def get(self, tenant_id: str) -> TenantDataPlane:
        plane = await self._session.scalar(select(TenantDataPlane).where(TenantDataPlane.tenant_id == tenant_id))
        if plane is None:
            raise TenantNotFound(tenant_id)
        return plane

    async def list_planes(self) -> list[TenantDataPlane]:
        return list((await self._session.scalars(select(TenantDataPlane).order_by(TenantDataPlane.id))).all())

    async def create(
        self,
        *,
        tenant_id: str,
        tenant_name: str,
        allowed_onprem_cidrs: list[str],
        org_tenant_id: int | None = None,
        routing_type: str = "static",
        shared_ec2_instance_id: str | None = None,
        shared_services_vpc_id: str | None = None,
        teiid_api_key_secret_ref: str | None = None,
    ) -> tuple[TenantDataPlane, TenantLayout]:
        tid = validate_tenant_id(tenant_id)
        existing = await self._session.scalar(select(TenantDataPlane).where(TenantDataPlane.tenant_id == tid))
        if existing is not None:
            raise TenantAlreadyExists(tid)

        index = await self._next_index()
        layout = compute_layout(tid, index)

        plane = TenantDataPlane(
            tenant_id=tid,
            tenant_name=tenant_name,
            org_tenant_id=org_tenant_id,
            isolation_mode=DEFAULT_ISOLATION_MODE,
            shared_ec2_instance_id=shared_ec2_instance_id,
            shared_services_vpc_id=shared_services_vpc_id,
            routing_type=routing_type,
            docker_network_name=layout.docker_network_name,
            docker_subnet_cidr=layout.docker_subnet_cidr,
            teiid_container_name=layout.teiid_container_name,
            teiid_container_ip=layout.teiid_container_ip,
            teiid_servlet_url=layout.teiid_servlet_url,
            teiid_pg_host=layout.teiid_pg_host,
            teiid_pg_port=layout.host_pg_port,
            teiid_mgmt_port=layout.host_mgmt_port,
            vdb_host_path=layout.vdb_host_path,
            allowed_onprem_cidrs=allowed_onprem_cidrs,
            status="provisioning",
        )
        self._session.add(plane)
        await self._session.flush()

        # Store a *reference* to the Teiid API key secret (never the value).
        default_ref = teiid_api_key_secret_ref or f"env:TENANT_{tid.upper().replace('-', '_')}_TEIID_API_KEY"
        self._session.add(
            TenantSecretRef(
                tenant_id=tid,
                data_plane_id=plane.id,
                secret_name="teiid_api_key",
                secret_ref=default_ref,
            )
        )
        await self._session.flush()
        return plane, layout

    async def attach_vpn_metadata(self, tenant_id: str, meta: VpnMetadata) -> TenantDataPlane:
        plane = await self.get(tenant_id)
        for fieldname in (
            "tenant_vpc_id",
            "tenant_subnet_id",
            "tenant_route_table_id",
            "customer_gateway_id",
            "vpn_connection_id",
            "vpn_tunnel1_address",
            "vpn_tunnel2_address",
            "shared_services_vpc_id",
            "shared_ec2_instance_id",
            "routing_type",
        ):
            value = getattr(meta, fieldname)
            if value is not None:
                setattr(plane, fieldname, value)
        await self._session.flush()
        return plane

    def layout_for(self, plane: TenantDataPlane) -> TenantLayout:
        """Reconstruct the layout for an existing plane from its subnet index."""
        third = int(plane.docker_subnet_cidr.split(".")[2])
        return compute_layout(plane.tenant_id, third // 10)

    def render_compose(self, plane: TenantDataPlane) -> str:
        return TenantComposeService().render(self.layout_for(plane))

    async def render_firewall_script(self) -> str:
        """Render the combined firewall script across all registered tenants."""
        planes = await self.list_planes()
        specs = [
            TenantFirewallSpec(
                tenant_id=p.tenant_id,
                docker_subnet_cidr=p.docker_subnet_cidr,
                chain=self.layout_for(p).firewall_chain,
                allowed_onprem_cidrs=list(p.allowed_onprem_cidrs or []),
            )
            for p in planes
        ]
        return TenantFirewallService().render_script(specs)
