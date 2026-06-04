# ---------------------------------------------------------------------------
# Per-tenant data-plane networking.
#
# For each tenant this creates:
#   * a dedicated tenant VPC + private subnet + route table (isolation story,
#     audit surface, and home for future tenant-resident resources)
#   * a Customer Gateway describing the customer's on-prem VPN endpoint
#   * an AWS Site-to-Site VPN connection attached to the shared Transit Gateway
#   * a dedicated TGW route table for this tenant (so tenant A cannot route to
#     tenant B)
#   * the forward route (shared VPC -> tenant on-prem CIDRs via this VPN) and
#     the return route (tenant VPN -> shared VPC CIDR)
#
# The VPN terminates on the shared Transit Gateway rather than on a VPC virtual
# private gateway, which is the AWS-recommended pattern when the data path needs
# to transit from the shared services VPC out to on-prem.
# ---------------------------------------------------------------------------

locals {
  name_prefix     = "tablescope-tenant-${var.tenant_id}"
  static_routes   = var.vpn_routing_type == "static"
  onprem_cidr_map = { for idx, cidr in var.customer_onprem_cidrs : tostring(idx) => cidr }
}

# --- Tenant VPC -------------------------------------------------------------

resource "aws_vpc" "tenant" {
  cidr_block           = var.tenant_vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name      = "${local.name_prefix}-vpc"
    Tenant    = var.tenant_id
    ManagedBy = "tablescope-tenant-dataplane"
  }
}

resource "aws_subnet" "tenant_private" {
  vpc_id            = aws_vpc.tenant.id
  cidr_block        = var.tenant_private_subnet_cidr
  availability_zone = var.availability_zone

  tags = {
    Name      = "${local.name_prefix}-private"
    Tenant    = var.tenant_id
    ManagedBy = "tablescope-tenant-dataplane"
  }
}

resource "aws_route_table" "tenant" {
  vpc_id = aws_vpc.tenant.id

  tags = {
    Name      = "${local.name_prefix}-rt"
    Tenant    = var.tenant_id
    ManagedBy = "tablescope-tenant-dataplane"
  }
}

resource "aws_route_table_association" "tenant" {
  subnet_id      = aws_subnet.tenant_private.id
  route_table_id = aws_route_table.tenant.id
}

# Security group placeholder for future tenant-resident resources. Tenant
# egress for containers on the shared host is enforced by the host firewall;
# this SG documents the intended customer/on-prem access at the VPC layer.
resource "aws_security_group" "tenant" {
  name_prefix = "${local.name_prefix}-"
  description = "Tablescope tenant ${var.tenant_id} data-plane SG (placeholder)"
  vpc_id      = aws_vpc.tenant.id

  egress {
    description = "Allow egress to tenant on-prem CIDRs"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = var.customer_onprem_cidrs
  }

  tags = {
    Name      = "${local.name_prefix}-sg"
    Tenant    = var.tenant_id
    ManagedBy = "tablescope-tenant-dataplane"
  }
}

# --- Customer Gateway + Site-to-Site VPN -----------------------------------

resource "aws_customer_gateway" "tenant" {
  bgp_asn    = var.customer_bgp_asn
  ip_address = var.customer_gateway_ip
  type       = "ipsec.1"

  tags = {
    Name      = "${local.name_prefix}-cgw"
    Tenant    = var.tenant_id
    ManagedBy = "tablescope-tenant-dataplane"
  }
}

resource "aws_vpn_connection" "tenant" {
  customer_gateway_id = aws_customer_gateway.tenant.id
  transit_gateway_id  = var.transit_gateway_id
  type                = "ipsec.1"
  static_routes_only  = local.static_routes

  tags = {
    Name      = "${local.name_prefix}-vpn"
    Tenant    = var.tenant_id
    ManagedBy = "tablescope-tenant-dataplane"
  }
}

# --- Per-tenant TGW route table (isolation) --------------------------------

resource "aws_ec2_transit_gateway_route_table" "tenant" {
  transit_gateway_id = var.transit_gateway_id

  tags = {
    Name      = "${local.name_prefix}-tgw-rt"
    Tenant    = var.tenant_id
    ManagedBy = "tablescope-tenant-dataplane"
  }
}

# The VPN attachment (auto-created by the VPN connection) is associated with the
# tenant's own TGW route table so its only known destination is the shared VPC.
resource "aws_ec2_transit_gateway_route_table_association" "tenant_vpn" {
  transit_gateway_attachment_id  = aws_vpn_connection.tenant.transit_gateway_attachment_id
  transit_gateway_route_table_id = aws_ec2_transit_gateway_route_table.tenant.id
}

# Return path: from on-prem (arriving on this VPN) back to the shared services VPC.
resource "aws_ec2_transit_gateway_route" "tenant_to_shared" {
  destination_cidr_block         = var.shared_vpc_cidr
  transit_gateway_attachment_id  = var.shared_attachment_id
  transit_gateway_route_table_id = aws_ec2_transit_gateway_route_table.tenant.id
}

# Forward path: from the shared services VPC out to this tenant's on-prem
# CIDR(s) via this tenant's VPN attachment. Added to the SHARED TGW route table.
resource "aws_ec2_transit_gateway_route" "shared_to_onprem" {
  for_each = local.onprem_cidr_map

  destination_cidr_block         = each.value
  transit_gateway_attachment_id  = aws_vpn_connection.tenant.transit_gateway_attachment_id
  transit_gateway_route_table_id = var.shared_route_table_id
}
