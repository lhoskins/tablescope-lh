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

    # --- Optional unified provisioning fields ---
    # When provided, the data-plane create endpoint also creates an application
    # tenant (slug + root admin user) and binds them via org_tenant_id, so one
    # API call delivers a fully usable, login-ready tenant.
    create_app_tenant: bool = Field(
        default=False, description="If true, also create the application tenant and root admin user."
    )
    app_tenant_admin_email: str | None = Field(
        default=None, description="Root admin email for the new app tenant (required when create_app_tenant=true)."
    )
    app_tenant_admin_password: str | None = Field(
        default=None, description="Root admin password (required when create_app_tenant=true)."
    )


class BindAppTenantIn(BaseModel):
    """Bind an existing data plane to an application tenant.

    Either link an existing org tenant by id, or create a new app tenant
    (slug + root admin). VDBs are (re)provisioned in the data plane's container.
    """

    org_tenant_id: int | None = Field(
        default=None, description="Link to this existing application tenant id."
    )
    new_tenant_slug: str | None = Field(
        default=None, description="Slug for a new application tenant to create and bind."
    )
    new_tenant_name: str | None = None
    admin_email: str | None = Field(
        default=None, description="Root admin email (required with new_tenant_slug)."
    )
    admin_password: str | None = Field(
        default=None, description="Root admin password (required with new_tenant_slug)."
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
