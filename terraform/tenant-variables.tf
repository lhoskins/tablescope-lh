variable "tenants" {
  description = <<-EOT
    Map of tenant data planes to provision, keyed by tenant_id. Empty by
    default (no tenant infrastructure created). Each tenant gets its own VPC,
    private subnet, Customer Gateway, Site-to-Site VPN (attached to the shared
    Transit Gateway), and an isolated TGW route table.

    Constraints:
      * tenant_vpc_cidr / tenant_private_subnet_cidr must not overlap each
        other, other tenants, or the shared services VPC.
      * customer_onprem_cidrs must not overlap other tenants (MVP rule 4).
  EOT
  type = map(object({
    tenant_vpc_cidr            = string
    tenant_private_subnet_cidr = string
    customer_gateway_ip        = string
    customer_onprem_cidrs      = list(string)
    customer_bgp_asn           = optional(number, 65000)
    vpn_routing_type           = optional(string, "static")
  }))
  default = {}
}
