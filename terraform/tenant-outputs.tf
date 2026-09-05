output "transit_gateway_id" {
  description = "Shared Transit Gateway ID (null when no tenants configured)."
  value       = local.tenants_enabled ? module.network_hub[0].transit_gateway_id : null
}

output "tenant_data_planes" {
  description = "Per-tenant network/VPN metadata for the platform tenant registry."
  value = {
    for tid, m in module.tenant : tid => {
      tenant_vpc_id         = m.tenant_vpc_id
      tenant_subnet_id      = m.tenant_subnet_id
      tenant_route_table_id = m.tenant_route_table_id
      customer_gateway_id   = m.customer_gateway_id
      vpn_connection_id     = m.vpn_connection_id
      vpn_tunnel1_address   = m.vpn_tunnel1_address
      vpn_tunnel2_address   = m.vpn_tunnel2_address
      tenant_onprem_cidrs   = m.tenant_onprem_cidrs
      storage               = m.storage
    }
  }
}
