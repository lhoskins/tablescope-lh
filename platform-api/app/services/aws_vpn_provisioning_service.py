"""Runtime provisioning of AWS-side tenant VPN resources.

This service mirrors the intent of ``terraform/modules/tenant-vpc`` but is
designed to be called from the application after a tenant admin submits the
customer network details on the VPN onboarding page. It is idempotent via
``ManagedBy=tablescope-tenant-dataplane`` and ``Tenant=<tenant_id>`` tags.
"""

from __future__ import annotations

import ipaddress
import logging
from dataclasses import dataclass
from typing import Any

import boto3
from botocore.exceptions import ClientError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant_data_plane import TenantDataPlane
from app.services.tenant_provisioning_service import TenantProvisioningService, VpnMetadata

logger = logging.getLogger(__name__)

TAG_MANAGED_BY = "tablescope-tenant-dataplane"


class VpnProvisioningError(RuntimeError):
    """Raised when AWS VPN resource creation fails in a non-idempotent way."""


@dataclass(frozen=True, slots=True)
class SharedNetwork:
    tgw_id: str
    shared_vpc_id: str
    shared_vpc_cidr: str
    shared_subnet_id: str
    shared_route_table_id: str
    shared_tgw_route_table_id: str
    shared_tgw_attachment_id: str


class AwsVpnProvisioningService:
    """Create or re-use the AWS tenant VPC, Customer Gateway and Site-to-Site VPN.

    The shared Transit Gateway and shared services VPC are discovered by AWS
    tags (or by explicit IDs on the ``TenantDataPlane`` row). Tenant-side
    resources are created with deterministic, non-overlapping CIDRs derived
    from the tenant's Docker subnet index.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._ec2 = boto3.client("ec2")

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _tags(tenant_id: str, name: str) -> list[dict[str, str]]:
        return [
            {"Key": "Name", "Value": name},
            {"Key": "Tenant", "Value": tenant_id},
            {"Key": "ManagedBy", "Value": TAG_MANAGED_BY},
        ]

    @staticmethod
    def _tag_spec(resource_type: str, tags: list[dict[str, str]]) -> dict[str, Any]:
        return {"ResourceType": resource_type, "Tags": tags}

    # ----------------------------------------------------------- shared lookup

    async def _get_plane(self, tenant_id: str) -> TenantDataPlane:
        plane = await self._session.scalar(
            select(TenantDataPlane).where(TenantDataPlane.tenant_id == tenant_id)
        )
        if plane is None:
            raise VpnProvisioningError(f"TenantDataPlane not found for {tenant_id}")
        return plane

    async def _shared_network(self, plane: TenantDataPlane) -> SharedNetwork:
        """Discover the shared TGW, shared VPC, route tables and attachment."""
        tgw_id = await self._resolve_shared_tgw()
        shared_vpc_id = await self._resolve_shared_vpc(plane)
        shared_vpc_cidr = self._vpc_cidr(shared_vpc_id)

        shared_ec2_instance_id = await self._resolve_shared_ec2_instance(plane)
        shared_subnet_id = await self._resolve_shared_subnet(
            shared_vpc_id, shared_ec2_instance_id
        )

        shared_route_table_id = self._route_table_for_subnet(shared_subnet_id)
        shared_tgw_attachment_id = self._shared_tgw_attachment(tgw_id, shared_vpc_id)
        shared_tgw_route_table_id = self._shared_tgw_route_table(
            tgw_id, shared_tgw_attachment_id
        )

        # Persist the discovered shared IDs for diagnostics / teardown.
        plane.shared_services_vpc_id = shared_vpc_id
        plane.shared_ec2_instance_id = shared_ec2_instance_id
        await self._session.flush()

        return SharedNetwork(
            tgw_id=tgw_id,
            shared_vpc_id=shared_vpc_id,
            shared_vpc_cidr=shared_vpc_cidr,
            shared_subnet_id=shared_subnet_id,
            shared_route_table_id=shared_route_table_id,
            shared_tgw_route_table_id=shared_tgw_route_table_id,
            shared_tgw_attachment_id=shared_tgw_attachment_id,
        )

    async def _resolve_shared_tgw(self) -> str:
        """Find the shared Tablescope Transit Gateway by tag."""
        resp = self._ec2.describe_transit_gateways(
            Filters=[
                {"Name": "tag:Name", "Values": ["tablescope-tgw-hub"]},
                {"Name": "tag:ManagedBy", "Values": [TAG_MANAGED_BY]},
            ]
        )
        tgws = [t for t in resp.get("TransitGateways", []) if t.get("State") == "available"]
        if not tgws:
            raise VpnProvisioningError("No Tablescope Transit Gateway found")
        return tgws[0]["TransitGatewayId"]

    async def _resolve_shared_vpc(self, plane: TenantDataPlane) -> str:
        if plane.shared_services_vpc_id:
            return plane.shared_services_vpc_id
        resp = self._ec2.describe_vpcs(
            Filters=[
                {"Name": "tag:Name", "Values": ["tablescope"]},
                {"Name": "tag:ManagedBy", "Values": [TAG_MANAGED_BY]},
            ]
        )
        vpcs = resp.get("Vpcs", [])
        if not vpcs:
            # Fall back to the default VPC as a last resort.
            resp = self._ec2.describe_vpcs(
                Filters=[{"Name": "is-default", "Values": ["true"]}]
            )
            vpcs = resp.get("Vpcs", [])
        if not vpcs:
            raise VpnProvisioningError("No shared/default VPC found")
        return vpcs[0]["VpcId"]

    async def _resolve_shared_ec2_instance(self, plane: TenantDataPlane) -> str:
        if plane.shared_ec2_instance_id:
            return plane.shared_ec2_instance_id
        resp = self._ec2.describe_instances(
            Filters=[
                {"Name": "instance-state-name", "Values": ["running"]},
                {"Name": "tag:Name", "Values": ["tablescope"]},
            ]
        )
        for reservation in resp.get("Reservations", []):
            for inst in reservation.get("Instances", []):
                return inst["InstanceId"]
        raise VpnProvisioningError("No running Tablescope EC2 instance found")

    async def _resolve_shared_subnet(
        self, shared_vpc_id: str, shared_ec2_instance_id: str | None
    ) -> str:
        if shared_ec2_instance_id:
            resp = self._ec2.describe_instances(InstanceIds=[shared_ec2_instance_id])
            for reservation in resp.get("Reservations", []):
                for inst in reservation.get("Instances", []):
                    return inst["SubnetId"]
        resp = self._ec2.describe_subnets(
            Filters=[
                {"Name": "vpc-id", "Values": [shared_vpc_id]},
                {"Name": "map-public-ip-on-launch", "Values": ["true"]},
            ]
        )
        subnets = resp.get("Subnets", [])
        if not subnets:
            raise VpnProvisioningError("No public subnet found in shared VPC")
        return subnets[0]["SubnetId"]

    def _vpc_cidr(self, vpc_id: str) -> str:
        resp = self._ec2.describe_vpcs(VpcIds=[vpc_id])
        vpcs = resp.get("Vpcs", [])
        if not vpcs:
            raise VpnProvisioningError(f"VPC {vpc_id} not found")
        return vpcs[0]["CidrBlock"]

    def _route_table_for_subnet(self, subnet_id: str) -> str:
        resp = self._ec2.describe_route_tables(
            Filters=[{"Name": "association.subnet-id", "Values": [subnet_id]}]
        )
        tables = resp.get("RouteTables", [])
        if tables:
            return tables[0]["RouteTableId"]
        # Fall back to the main route table of the VPC.
        resp = self._ec2.describe_subnets(SubnetIds=[subnet_id])
        vpc_id = resp["Subnets"][0]["VpcId"]
        resp = self._ec2.describe_route_tables(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )
        for table in resp.get("RouteTables", []):
            if any(a.get("Main") for a in table.get("Associations", [])):
                return table["RouteTableId"]
        raise VpnProvisioningError(f"No route table found for subnet {subnet_id}")

    def _shared_tgw_attachment(self, tgw_id: str, shared_vpc_id: str) -> str:
        resp = self._ec2.describe_transit_gateway_vpc_attachments(
            Filters=[
                {"Name": "transit-gateway-id", "Values": [tgw_id]},
                {"Name": "vpc-id", "Values": [shared_vpc_id]},
            ]
        )
        attachments = [
            a
            for a in resp.get("TransitGatewayVpcAttachments", [])
            if a.get("State") == "available"
        ]
        if not attachments:
            raise VpnProvisioningError(
                f"No Transit Gateway VPC attachment for {shared_vpc_id}"
            )
        return attachments[0]["TransitGatewayAttachmentId"]

    def _shared_tgw_route_table(self, tgw_id: str, shared_attachment_id: str) -> str:
        """Find the TGW route table that the shared VPC attachment is associated with."""
        tables = self._ec2.describe_transit_gateway_route_tables(
            Filters=[{"Name": "transit-gateway-id", "Values": [tgw_id]}]
        ).get("TransitGatewayRouteTables", [])
        for table in tables:
            if table.get("State") != "available":
                continue
            assoc = self._ec2.get_transit_gateway_route_table_associations(
                TransitGatewayRouteTableId=table["TransitGatewayRouteTableId"]
            ).get("Associations", [])
            if any(
                a.get("TransitGatewayAttachmentId") == shared_attachment_id
                for a in assoc
            ):
                return table["TransitGatewayRouteTableId"]
        raise VpnProvisioningError("No TGW route table associated with shared VPC")

    def _subnet_az(self, subnet_id: str) -> str:
        resp = self._ec2.describe_subnets(SubnetIds=[subnet_id])
        subnets = resp.get("Subnets", [])
        if not subnets:
            raise VpnProvisioningError(f"Subnet {subnet_id} not found")
        return subnets[0]["AvailabilityZone"]

    # ----------------------------------------------------------- CIDR planning

    @staticmethod
    def _docker_index(plane: TenantDataPlane) -> int:
        """Extract the tenant layout index from the Docker subnet.

        ``compute_layout`` uses ``172.30.<10*index>.0/24``.
        """
        cidr = plane.docker_subnet_cidr
        try:
            third = int(ipaddress.ip_network(cidr).network_address.packed[-2])
        except ValueError as exc:
            raise VpnProvisioningError(f"Invalid docker_subnet_cidr {cidr}") from exc
        index = third // 10
        if index < 1 or index > 250:
            raise VpnProvisioningError(f"Docker subnet index out of range: {index}")
        return index

    def _allocate_tenant_cidrs(
        self, tenant_id: str, index: int, onprem_cidrs: list[str]
    ) -> tuple[str, str]:
        """Return a tenant VPC CIDR and private subnet CIDR that do not overlap existing VPCs or the on-prem CIDRs."""
        # Reuse an already-provisioned tenant VPC when re-running.
        tenant_vpcs = self._ec2.describe_vpcs(
            Filters=[{"Name": "tag:Tenant", "Values": [tenant_id]}]
        ).get("Vpcs", [])
        if len(tenant_vpcs) > 1:
            ids = [v["VpcId"] for v in tenant_vpcs]
            raise VpnProvisioningError(f"Multiple tenant VPCs for {tenant_id}: {ids}")
        if tenant_vpcs:
            vpc_cidr = tenant_vpcs[0]["CidrBlock"]
            third = int(ipaddress.ip_network(vpc_cidr).network_address.packed[-2])
            private = f"10.{third}.1.0/24"
            return vpc_cidr, private

        existing = self._existing_vpc_cidrs()
        forbidden = set(ipaddress.ip_network(c) for c in onprem_cidrs if c)
        # Start at 10.20+index to avoid common home-lab ranges.
        for offset in range(0, 230 - index):
            candidate = f"10.{20 + index + offset}.0.0/16"
            network = ipaddress.ip_network(candidate)
            if any(network.overlaps(ipaddress.ip_network(e)) for e in existing):
                continue
            if any(network.overlaps(f) for f in forbidden):
                continue
            private = f"10.{20 + index + offset}.1.0/24"
            return candidate, private
        raise VpnProvisioningError("Unable to allocate a non-overlapping tenant VPC CIDR")

    def _existing_vpc_cidrs(self) -> set[str]:
        resp = self._ec2.describe_vpcs()
        cidrs: set[str] = set()
        for vpc in resp.get("Vpcs", []):
            for cidr_assoc in vpc.get("CidrBlockAssociationSet", []):
                cidrs.add(cidr_assoc["CidrBlock"])
            cidrs.add(vpc["CidrBlock"])
        return cidrs

    # ----------------------------------------------------------- resource CRUD

    def _get_or_create_vpc(self, tenant_id: str, cidr: str) -> str:
        existing = self._ec2.describe_vpcs(
            Filters=[
                {"Name": "tag:Tenant", "Values": [tenant_id]},
            ]
        )
        if existing.get("Vpcs"):
            if len(existing["Vpcs"]) > 1:
                ids = [v["VpcId"] for v in existing["Vpcs"]]
                raise VpnProvisioningError(
                    f"Multiple tenant VPCs for {tenant_id}: {ids}; cannot pick safely"
                )
            return existing["Vpcs"][0]["VpcId"]

        resp = self._ec2.create_vpc(
            CidrBlock=cidr,
            TagSpecifications=[
                self._tag_spec("vpc", self._tags(tenant_id, f"tablescope-tenant-{tenant_id}-vpc"))
            ],
        )
        vpc_id = resp["Vpc"]["VpcId"]
        self._ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsSupport={"Value": True})
        self._ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsHostnames={"Value": True})
        logger.info("Created tenant VPC %s for %s", vpc_id, tenant_id)
        return vpc_id

    def _get_or_create_subnet(
        self, tenant_id: str, vpc_id: str, cidr: str, az: str
    ) -> str:
        existing = self._ec2.describe_subnets(
            Filters=[
                {"Name": "vpc-id", "Values": [vpc_id]},
                {"Name": "cidr-block", "Values": [cidr]},
                {"Name": "tag:Tenant", "Values": [tenant_id]},
            ]
        )
        if existing.get("Subnets"):
            return existing["Subnets"][0]["SubnetId"]

        resp = self._ec2.create_subnet(
            VpcId=vpc_id,
            CidrBlock=cidr,
            AvailabilityZone=az,
            TagSpecifications=[
                self._tag_spec(
                    "subnet",
                    self._tags(tenant_id, f"tablescope-tenant-{tenant_id}-private"),
                )
            ],
        )
        return resp["Subnet"]["SubnetId"]

    def _get_or_create_route_table(self, tenant_id: str, vpc_id: str) -> str:
        existing = self._ec2.describe_route_tables(
            Filters=[
                {"Name": "vpc-id", "Values": [vpc_id]},
                {"Name": "tag:Tenant", "Values": [tenant_id]},
            ]
        )
        if existing.get("RouteTables"):
            return existing["RouteTables"][0]["RouteTableId"]

        resp = self._ec2.create_route_table(
            VpcId=vpc_id,
            TagSpecifications=[
                self._tag_spec(
                    "route-table",
                    self._tags(tenant_id, f"tablescope-tenant-{tenant_id}-rt"),
                )
            ],
        )
        return resp["RouteTable"]["RouteTableId"]

    def _get_or_create_security_group(
        self, tenant_id: str, vpc_id: str, onprem_cidrs: list[str]
    ) -> str:
        existing = self._ec2.describe_security_groups(
            Filters=[
                {"Name": "vpc-id", "Values": [vpc_id]},
                {"Name": "tag:Tenant", "Values": [tenant_id]},
            ]
        )
        if existing.get("SecurityGroups"):
            return existing["SecurityGroups"][0]["GroupId"]

        resp = self._ec2.create_security_group(
            GroupName=f"tablescope-tenant-{tenant_id}",
            Description=f"Tablescope tenant {tenant_id} data-plane SG",
            VpcId=vpc_id,
            TagSpecifications=[
                self._tag_spec(
                    "security-group",
                    self._tags(tenant_id, f"tablescope-tenant-{tenant_id}-sg"),
                )
            ],
        )
        group_id = resp["GroupId"]
        if onprem_cidrs:
            self._ec2.authorize_security_group_egress(
                GroupId=group_id,
                IpPermissions=[
                    {
                        "IpProtocol": "-1",
                        "IpRanges": [{"CidrIp": c} for c in onprem_cidrs],
                    }
                ],
            )
        return group_id

    def _get_or_create_customer_gateway(
        self, tenant_id: str, public_ip: str, bgp_asn: int = 65000
    ) -> str:
        resp = self._ec2.describe_customer_gateways(
            Filters=[
                {"Name": "ip-address", "Values": [public_ip]},
                {"Name": "tag:Tenant", "Values": [tenant_id]},
            ]
        )
        for cgw in resp.get("CustomerGateways", []):
            if cgw.get("State") in ("available", "pending"):
                return cgw["CustomerGatewayId"]

        resp = self._ec2.create_customer_gateway(
            BgpAsn=bgp_asn,
            IpAddress=public_ip,
            Type="ipsec.1",
            TagSpecifications=[
                self._tag_spec(
                    "customer-gateway",
                    self._tags(tenant_id, f"tablescope-tenant-{tenant_id}-cgw"),
                )
            ],
        )
        return resp["CustomerGateway"]["CustomerGatewayId"]

    def _get_or_create_vpn_connection(
        self,
        tenant_id: str,
        customer_gateway_id: str,
        tgw_id: str,
        static: bool,
    ) -> tuple[str, str, str, str]:
        """Return (vpn_id, tgw_attachment_id, tunnel1_ip, tunnel2_ip)."""
        resp = self._ec2.describe_vpn_connections(
            Filters=[
                {"Name": "transit-gateway-id", "Values": [tgw_id]},
                {"Name": "customer-gateway-id", "Values": [customer_gateway_id]},
                {"Name": "tag:Tenant", "Values": [tenant_id]},
            ]
        )
        for vpn in resp.get("VpnConnections", []):
            if vpn.get("State") in ("pending", "available"):
                vpn_id = vpn["VpnConnectionId"]
                tgw_attachment_id = self._wait_for_vpn_attachment(vpn_id)
                tunnel1, tunnel2 = self._wait_for_tunnel_ips(vpn_id)
                return vpn_id, tgw_attachment_id, tunnel1, tunnel2

        options: dict[str, Any] = {"StaticRoutesOnly": static}
        resp = self._ec2.create_vpn_connection(
            CustomerGatewayId=customer_gateway_id,
            TransitGatewayId=tgw_id,
            Type="ipsec.1",
            Options=options,
            TagSpecifications=[
                self._tag_spec(
                    "vpn-connection",
                    self._tags(tenant_id, f"tablescope-tenant-{tenant_id}-vpn"),
                )
            ],
        )
        vpn_id = resp["VpnConnection"]["VpnConnectionId"]
        # Wait until the TGW attachment is created.
        tgw_attachment_id = self._wait_for_vpn_attachment(vpn_id)
        tunnel1, tunnel2 = self._wait_for_tunnel_ips(vpn_id)
        return vpn_id, tgw_attachment_id, tunnel1, tunnel2

    def _wait_for_vpn_attachment(self, vpn_id: str) -> str:
        import time

        for _ in range(120):
            resp = self._ec2.describe_transit_gateway_attachments(
                Filters=[
                    {"Name": "resource-id", "Values": [vpn_id]},
                    {"Name": "resource-type", "Values": ["vpn"]},
                ]
            )
            attachments = [
                a
                for a in resp.get("TransitGatewayAttachments", [])
                if a.get("State") == "available"
            ]
            if attachments:
                return attachments[0]["TransitGatewayAttachmentId"]
            time.sleep(5)
        raise VpnProvisioningError(f"VPN {vpn_id} did not create TGW attachment")

    def _wait_for_tunnel_ips(self, vpn_id: str) -> tuple[str, str]:
        import time

        for _ in range(60):
            resp = self._ec2.describe_vpn_connections(VpnConnectionIds=[vpn_id])
            vpn = resp["VpnConnections"][0]
            tunnel1, tunnel2 = self._tunnel_ips(vpn)
            if tunnel1 and tunnel2:
                return tunnel1, tunnel2
            time.sleep(2)
        raise VpnProvisioningError(f"VPN {vpn_id} did not expose tunnel IPs")

    @staticmethod
    def _tunnel_ips(vpn: dict[str, Any]) -> tuple[str, str]:
        options = vpn.get("Options", {})
        tunnels = options.get("TunnelOptions", [])
        if len(tunnels) >= 2:
            return tunnels[0].get("OutsideIpAddress", ""), tunnels[1].get(
                "OutsideIpAddress", ""
            )
        # Fallback to VgwTelemetry if the tunnels are not yet in Options.
        telemetry = vpn.get("VgwTelemetry", [])
        if len(telemetry) >= 2:
            return telemetry[0].get("OutsideIpAddress", ""), telemetry[1].get(
                "OutsideIpAddress", ""
            )
        return "", ""

    def _get_or_create_tenant_tgw_route_table(
        self, tenant_id: str, tgw_id: str
    ) -> str:
        resp = self._ec2.describe_transit_gateway_route_tables(
            Filters=[
                {"Name": "transit-gateway-id", "Values": [tgw_id]},
                {"Name": "tag:Tenant", "Values": [tenant_id]},
            ]
        )
        tables = [t for t in resp.get("TransitGatewayRouteTables", []) if t.get("State") == "available"]
        if tables:
            return tables[0]["TransitGatewayRouteTableId"]

        resp = self._ec2.create_transit_gateway_route_table(
            TransitGatewayId=tgw_id,
            TagSpecifications=[
                self._tag_spec(
                    "transit-gateway-route-table",
                    self._tags(tenant_id, f"tablescope-tenant-{tenant_id}-tgw-rt"),
                )
            ],
        )
        return resp["TransitGatewayRouteTable"]["TransitGatewayRouteTableId"]

    # ----------------------------------------------------------------- routing

    def _ensure_route(
        self, route_table_id: str, dest: str, **target: Any
    ) -> None:
        """Idempotent AWS route creation."""
        try:
            self._ec2.create_route(
                RouteTableId=route_table_id,
                DestinationCidrBlock=dest,
                **target,
            )
        except ClientError as exc:
            err = exc.response.get("Error", {})
            if err.get("Code") == "RouteAlreadyExists":
                logger.debug("Route %s already exists in %s", dest, route_table_id)
                return
            raise VpnProvisioningError(str(exc)) from exc

    def _ensure_tgw_route(
        self, route_table_id: str, dest: str, attachment_id: str
    ) -> None:
        """Idempotent TGW route creation; ignores duplicate."""
        try:
            self._ec2.create_transit_gateway_route(
                TransitGatewayRouteTableId=route_table_id,
                DestinationCidrBlock=dest,
                TransitGatewayAttachmentId=attachment_id,
            )
        except ClientError as exc:
            err = exc.response.get("Error", {})
            if err.get("Code") in ("RouteAlreadyExists", "IncorrectState"):
                return
            raise VpnProvisioningError(str(exc)) from exc

    # ----------------------------------------------------------------- public API

    async def provision(
        self,
        tenant_id: str,
        customer_gateway_ip: str,
        customer_onprem_cidrs: list[str],
        routing_type: str = "static",
    ) -> VpnMetadata:
        """Provision (or re-use) AWS resources for a tenant VPN.

        Returns a ``VpnMetadata`` object that callers should persist with
        ``TenantProvisioningService.attach_vpn_metadata``.
        """
        plane = await self._get_plane(tenant_id)
        if plane.vpn_mode != "customer_vpn":
            raise VpnProvisioningError(f"Tenant {tenant_id} is not in customer_vpn mode")

        shared = await self._shared_network(plane)

        index = self._docker_index(plane)
        tenant_vpc_cidr, tenant_private_subnet_cidr = self._allocate_tenant_cidrs(
            tenant_id, index, customer_onprem_cidrs
        )

        az = self._subnet_az(shared.shared_subnet_id)
        vpc_id = self._get_or_create_vpc(tenant_id, tenant_vpc_cidr)
        subnet_id = self._get_or_create_subnet(
            tenant_id, vpc_id, tenant_private_subnet_cidr, az
        )
        route_table_id = self._get_or_create_route_table(tenant_id, vpc_id)
        self._ensure_route_table_association(subnet_id, route_table_id)

        # Placeholder SG for tenant-resident resources; egress controlled by host firewall.
        self._get_or_create_security_group(tenant_id, vpc_id, customer_onprem_cidrs)

        cgw_id = self._get_or_create_customer_gateway(
            tenant_id, customer_gateway_ip, bgp_asn=65000
        )

        static = routing_type == "static"
        vpn_id, vpn_attachment_id, tunnel1, tunnel2 = self._get_or_create_vpn_connection(
            tenant_id, cgw_id, shared.tgw_id, static
        )

        tenant_tgw_rt = self._get_or_create_tenant_tgw_route_table(tenant_id, shared.tgw_id)

        # Associate the VPN attachment with the tenant's own TGW route table.
        self._ensure_tgw_route_table_association(tenant_tgw_rt, vpn_attachment_id)

        # Return path: on-prem -> shared VPC CIDR via the shared VPC attachment.
        self._ensure_tgw_route(tenant_tgw_rt, shared.shared_vpc_cidr, shared.shared_tgw_attachment_id)

        # Forward path: shared services VPC -> on-prem CIDRs via the tenant VPN attachment.
        for cidr in customer_onprem_cidrs:
            self._ensure_tgw_route(shared.shared_tgw_route_table_id, cidr, vpn_attachment_id)
            self._ensure_route(
                shared.shared_route_table_id, cidr, TransitGatewayId=shared.tgw_id
            )

        # Build metadata and update the plane.
        meta = VpnMetadata(
            tenant_vpc_id=vpc_id,
            tenant_subnet_id=subnet_id,
            tenant_route_table_id=route_table_id,
            customer_gateway_id=cgw_id,
            vpn_connection_id=vpn_id,
            vpn_tunnel1_address=tunnel1,
            vpn_tunnel2_address=tunnel2,
            shared_services_vpc_id=shared.shared_vpc_id,
            shared_ec2_instance_id=plane.shared_ec2_instance_id or "",
            routing_type=routing_type,
        )

        provisioner = TenantProvisioningService(self._session)
        await provisioner.attach_vpn_metadata(tenant_id, meta)

        plane.allowed_onprem_cidrs = list(customer_onprem_cidrs)
        plane.vpn_status = "configured"
        await self._session.flush()

        logger.info(
            "AWS VPN provisioned for tenant=%s vpc=%s vpn=%s tunnels=%s,%s",
            tenant_id,
            vpc_id,
            vpn_id,
            tunnel1,
            tunnel2,
        )
        return meta

    def _ensure_route_table_association(self, subnet_id: str, route_table_id: str) -> None:
        """Associate the tenant subnet with the tenant route table if not already."""
        resp = self._ec2.describe_route_tables(
            Filters=[{"Name": "association.subnet-id", "Values": [subnet_id]}]
        )
        for rt in resp.get("RouteTables", []):
            for assoc in rt.get("Associations", []):
                if assoc.get("SubnetId") == subnet_id:
                    return
        self._ec2.associate_route_table(SubnetId=subnet_id, RouteTableId=route_table_id)

    def _ensure_tgw_route_table_association(
        self, route_table_id: str, attachment_id: str
    ) -> None:
        """Idempotent TGW route-table association."""
        try:
            self._ec2.associate_transit_gateway_route_table(
                TransitGatewayRouteTableId=route_table_id,
                TransitGatewayAttachmentId=attachment_id,
            )
        except ClientError as exc:
            err = exc.response.get("Error", {})
            if err.get("Code") in ("AlreadyExists", "Resource.AlreadyAssociated"):
                return
            raise VpnProvisioningError(str(exc)) from exc
