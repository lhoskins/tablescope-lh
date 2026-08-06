# ---------------------------------------------------------------------------
# Tenant data-plane wiring (Phase 1 of the Tenant VPN/Data-Plane plan).
#
# This is additive and OFF by default: with an empty `tenants` map no tenant
# infrastructure is created and the existing single-host EC2 deployment is
# untouched. Populate `tenants` (see terraform.tfvars.example) to provision a
# shared Transit Gateway plus one VPC + Site-to-Site VPN per tenant.
# ---------------------------------------------------------------------------

# Route table associated with the shared EC2 subnet (used to add on-prem routes
# pointing at the Transit Gateway).
data "aws_route_table" "shared" {
  count     = local.tenants_enabled ? 1 : 0
  subnet_id = local.subnet_id
}

locals {
  tenants_enabled    = length(var.tenants) > 0
  network_hub_enabled = var.enable_network_hub != null ? var.enable_network_hub : local.tenants_enabled

  # Flatten every tenant's on-prem CIDRs into route entries for the shared
  # subnet route table: { "<tenant>-<idx>" = { route_table_id, cidr } }.
  shared_onprem_routes = local.tenants_enabled ? merge([
    for tid, t in var.tenants : {
      for idx, cidr in t.customer_onprem_cidrs :
      "${tid}-${idx}" => {
        route_table_id = data.aws_route_table.shared[0].id
        cidr           = cidr
      }
    }
  ]...) : {}
}

module "network_hub" {
  source = "./modules/network-hub"
  count  = local.network_hub_enabled ? 1 : 0

  shared_vpc_id                   = data.aws_vpc.selected.id
  shared_subnet_ids               = [local.subnet_id]
  shared_route_table_onprem_cidrs = local.shared_onprem_routes
}

module "tenant" {
  source   = "./modules/tenant-vpc"
  for_each = var.tenants

  tenant_id                  = each.key
  availability_zone          = var.availability_zone
  tenant_vpc_cidr            = each.value.tenant_vpc_cidr
  tenant_private_subnet_cidr = each.value.tenant_private_subnet_cidr
  customer_gateway_ip        = each.value.customer_gateway_ip
  customer_bgp_asn           = each.value.customer_bgp_asn
  customer_onprem_cidrs      = each.value.customer_onprem_cidrs
  vpn_routing_type           = each.value.vpn_routing_type

  transit_gateway_id    = module.network_hub[0].transit_gateway_id
  shared_attachment_id  = module.network_hub[0].shared_attachment_id
  shared_route_table_id = module.network_hub[0].shared_route_table_id
  shared_vpc_cidr       = data.aws_vpc.selected.cidr_block
}
