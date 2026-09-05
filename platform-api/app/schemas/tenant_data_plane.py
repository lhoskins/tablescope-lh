"""Pydantic schemas for the tenant data-plane API."""

from __future__ import annotations

from urllib.parse import urlparse

from pydantic import BaseModel, Field, model_validator


class TenantDataPlaneCreate(BaseModel):
    tenant_id: str = Field(..., description="Stable lowercase slug, e.g. 'acme'.")
    tenant_name: str
    s3_region: str = Field(
        default="us-west-1",
        pattern=r"^[a-z]{2}(?:-gov)?-[a-z]+-\d$",
        description="AWS region for the tenant's dedicated S3 boundary.",
    )
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


class StorageMetadataIn(BaseModel):
    """Non-secret Terraform outputs that bind a plane to private S3."""

    s3_bucket_name: str = Field(pattern=r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
    s3_region: str = Field(pattern=r"^[a-z]{2}(?:-gov)?-[a-z]+-\d$")
    s3_prefix: str = Field(default="", max_length=500)
    s3_access_point_arn: str
    s3_vpc_endpoint_id: str
    s3_endpoint_url: str
    s3_kms_key_arn: str
    s3_role_arn: str
    s3_force_private: bool = True

    @model_validator(mode="after")
    def validate_private_boundary(self) -> StorageMetadataIn:
        metadata_values = (
            self.s3_prefix,
            self.s3_access_point_arn,
            self.s3_endpoint_url,
            self.s3_kms_key_arn,
            self.s3_role_arn,
        )
        if any(any(char in value for char in '\r\n\t"') for value in metadata_values):
            raise ValueError("storage metadata contains unsafe control characters")
        endpoint = urlparse(self.s3_endpoint_url)
        hostname = endpoint.hostname or ""
        if endpoint.scheme != "https" or not hostname.endswith(".amazonaws.com"):
            raise ValueError("s3_endpoint_url must be an HTTPS AWS endpoint")
        if self.s3_vpc_endpoint_id not in hostname:
            raise ValueError("s3_endpoint_url must name s3_vpc_endpoint_id")
        expected_ap_prefix = f"arn:aws:s3:{self.s3_region}:"
        if not self.s3_access_point_arn.startswith(expected_ap_prefix) or ":accesspoint/" not in self.s3_access_point_arn:
            raise ValueError("s3_access_point_arn must be an S3 access point ARN in s3_region")
        if not self.s3_kms_key_arn.startswith(f"arn:aws:kms:{self.s3_region}:"):
            raise ValueError("s3_kms_key_arn must be a KMS key ARN in s3_region")
        if not self.s3_role_arn.startswith("arn:aws:iam::") or ":role/" not in self.s3_role_arn:
            raise ValueError("s3_role_arn must be an IAM role ARN")
        if not self.s3_force_private:
            raise ValueError("s3_force_private must be true for an isolated data plane")
        return self


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
    storage_mode: str
    s3_bucket_name: str | None = None
    s3_region: str | None = None
    s3_prefix: str = ""
    s3_access_point_arn: str | None = None
    s3_vpc_endpoint_id: str | None = None
    s3_endpoint_url: str | None = None
    s3_kms_key_arn: str | None = None
    s3_role_arn: str | None = None
    s3_force_private: bool = True
    storage_status: str
    storage_validated_at: str | None = None
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


class DeleteDataPlaneResponse(BaseModel):
    tenant_id: str
    org_tenant_id: int | None = None
    app_tenant_deleted: bool
    deleted_rows: dict[str, int]
    folders_removed: bool
    teardown_script: str
    teardown_script_path: str | None = None
    note: str
