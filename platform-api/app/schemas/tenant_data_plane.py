"""Pydantic schemas for the tenant data-plane API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TenantDataPlaneCreate(BaseModel):
    tenant_id: str = Field(..., description="Stable lowercase slug, e.g. 'acme'.")
    tenant_name: str
    vpn_mode: str = Field(
        default="none",
        description="'none' (container-only, no VPN) or 'customer_vpn' "
        "(dedicated VPC + Site-to-Site VPN to the customer's on-prem network).",
    )
    allowed_onprem_cidrs: list[str] = Field(default_factory=list)
    org_tenant_id: int | None = None
    routing_type: str = "static"
    shared_ec2_instance_id: str | None = None
    shared_services_vpc_id: str | None = None
    teiid_api_key_secret_ref: str | None = Field(
        default=None,
        description="Reference to the Teiid API key secret (e.g. 'env:...' or an "
        "AWS Secrets Manager ARN). Never the secret value itself.",
    )


class VpnMetadataIn(BaseModel):
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


class TenantDataPlaneRead(BaseModel):
    id: int
    tenant_id: str
    tenant_name: str
    org_tenant_id: int | None
    isolation_mode: str
    vpn_mode: str
    docker_network_name: str
    docker_subnet_cidr: str
    teiid_container_name: str
    teiid_container_ip: str
    teiid_servlet_url: str
    teiid_pg_host: str
    teiid_pg_port: int
    teiid_mgmt_port: int | None
    vdb_host_path: str
    vdb_container_path: str
    allowed_onprem_cidrs: list[str]
    blocked_cidrs: list[str]
    status: str
    last_health_status: str | None
    last_health_message: str | None
    # Network metadata
    shared_ec2_instance_id: str | None = None
    shared_services_vpc_id: str | None = None
    tenant_vpc_id: str | None = None
    tenant_subnet_id: str | None = None
    tenant_route_table_id: str | None = None
    customer_gateway_id: str | None = None
    vpn_connection_id: str | None = None
    vpn_tunnel1_address: str | None = None
    vpn_tunnel2_address: str | None = None
    routing_type: str | None = None
    vpn_status: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ProvisionContainerResponse(BaseModel):
    tenant_id: str
    compose_path: str
    compose_content: str
    directories: list[str]
    note: str


class ComposePreview(BaseModel):
    tenant_id: str
    compose_path: str
    compose_content: str


class FirewallScriptPreview(BaseModel):
    script: str
    config_dir: str
    systemd_unit_path: str
    systemd_unit: str


class HealthCheckRequest(BaseModel):
    connectivity_targets: list[str] = Field(
        default_factory=list,
        description="Optional host:port targets to TCP-probe (e.g. '10.10.5.20:5432').",
    )


class OnboardingPackage(BaseModel):
    tenant_id: str
    tenant_name: str
    customer_gateway_id: str | None
    customer_gateway_ip: str | None
    aws_tunnel_outside_ips: list[str]
    routing_type: str
    allowed_onprem_cidrs: list[str]
    instructions: str
