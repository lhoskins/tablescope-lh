# ---------------------------------------------------------------------------
# Network hub — a single shared AWS Transit Gateway that connects the shared
# services VPC (where the EC2 host lives) to every tenant's Site-to-Site VPN.
#
# Why Transit Gateway and not VPC peering:
#   The shared EC2 host runs in the shared services VPC. Each tenant terminates
#   its Site-to-Site VPN in its own routing domain. For the EC2 host to reach a
#   customer's on-prem network through that tenant's VPN, traffic must transit
#   shared-VPC -> tenant-VPN. AWS VPC peering does NOT support this transitive
#   (edge-to-edge) routing through a VPN, so peering cannot deliver the data
#   path this architecture requires. Transit Gateway does, and a single shared
#   TGW with per-tenant route tables keeps cost low while enforcing tenant
#   isolation (tenant A's route table cannot reach tenant B).
# ---------------------------------------------------------------------------

resource "aws_ec2_transit_gateway" "hub" {
  description                     = "Tablescope shared tenant data-plane hub"
  amazon_side_asn                 = var.amazon_side_asn
  auto_accept_shared_attachments  = "disable"
  default_route_table_association = "disable"
  default_route_table_propagation = "disable"
  dns_support                     = "enable"
  vpn_ecmp_support                = "enable"

  tags = {
    Name      = "tablescope-tgw-hub"
    ManagedBy = "tablescope-tenant-dataplane"
  }
}

# Attach the shared services VPC (the VPC that hosts the EC2 instance).
resource "aws_ec2_transit_gateway_vpc_attachment" "shared" {
  transit_gateway_id = aws_ec2_transit_gateway.hub.id
  vpc_id             = var.shared_vpc_id
  subnet_ids         = var.shared_subnet_ids

  transit_gateway_default_route_table_association = false
  transit_gateway_default_route_table_propagation = false

  tags = {
    Name      = "tablescope-tgw-shared-vpc"
    ManagedBy = "tablescope-tenant-dataplane"
  }
}

# Route table the shared services VPC attachment is associated with. Each
# tenant module adds a static route here pointing that tenant's on-prem CIDR(s)
# at the tenant's VPN attachment, so the EC2 host can reach on-prem.
resource "aws_ec2_transit_gateway_route_table" "shared" {
  transit_gateway_id = aws_ec2_transit_gateway.hub.id

  tags = {
    Name      = "tablescope-tgw-shared-rt"
    ManagedBy = "tablescope-tenant-dataplane"
  }
}

resource "aws_ec2_transit_gateway_route_table_association" "shared" {
  transit_gateway_attachment_id  = aws_ec2_transit_gateway_vpc_attachment.shared.id
  transit_gateway_route_table_id = aws_ec2_transit_gateway_route_table.shared.id
}

# Add routes in each shared-VPC subnet route table so traffic destined for any
# tenant on-prem CIDR is sent to the Transit Gateway. The TGW shared route
# table then forwards it out the correct tenant VPN attachment.
resource "aws_route" "shared_to_tgw" {
  for_each = var.shared_route_table_onprem_cidrs

  route_table_id         = each.value.route_table_id
  destination_cidr_block = each.value.cidr
  transit_gateway_id     = aws_ec2_transit_gateway.hub.id
}
