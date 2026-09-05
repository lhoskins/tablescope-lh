variable "tenants" {
  description = <<-EOT
    Map of tenant data planes to provision, keyed by tenant_id. Empty by
    default (no tenant infrastructure created). Each tenant gets its own VPC,
    private subnet, private S3 endpoint/access point/bucket/CMK and isolated
    IAM role. VPN resources are optional.

    Constraints:
      * tenant_vpc_cidr / tenant_private_subnet_cidr must not overlap each
        other, other tenants, or the shared services VPC.
      * customer_onprem_cidrs must not overlap other tenants (MVP rule 4).
  EOT
  type = map(object({
    tenant_vpc_cidr            = string
    tenant_private_subnet_cidr = string
    vpn_mode                   = optional(string, "none")
    customer_gateway_ip        = optional(string)
    customer_onprem_cidrs      = optional(list(string), [])
    customer_bgp_asn           = optional(number, 65000)
    vpn_routing_type           = optional(string, "static")
    storage_bucket_name        = optional(string)
    storage_force_destroy      = optional(bool, false)
  }))
  default = {}

  validation {
    condition = alltrue([
      for tenant in values(var.tenants) : contains(["none", "customer_vpn"], tenant.vpn_mode)
    ])
    error_message = "vpn_mode must be none or customer_vpn."
  }

  validation {
    condition = alltrue([
      for tenant in values(var.tenants) : tenant.vpn_mode == "none" || tenant.customer_gateway_ip != null
    ])
    error_message = "customer_gateway_ip is required when vpn_mode is customer_vpn."
  }
}
