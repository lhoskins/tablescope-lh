output "tenant_vpc_id" {
  description = "Tenant VPC ID."
  value       = aws_vpc.tenant.id
}

output "tenant_subnet_id" {
  description = "Tenant private subnet ID."
  value       = aws_subnet.tenant_private.id
}

output "tenant_route_table_id" {
  description = "Tenant VPC route table ID."
  value       = aws_route_table.tenant.id
}

output "tenant_security_group_id" {
  description = "Tenant data-plane security group ID (placeholder)."
  value       = aws_security_group.tenant.id
}

output "customer_gateway_id" {
  description = "Customer gateway ID."
  value       = aws_customer_gateway.tenant.id
}

output "vpn_connection_id" {
  description = "Site-to-Site VPN connection ID."
  value       = aws_vpn_connection.tenant.id
}

output "vpn_transit_gateway_attachment_id" {
  description = "TGW attachment ID of the tenant VPN connection."
  value       = aws_vpn_connection.tenant.transit_gateway_attachment_id
}

output "vpn_tunnel1_address" {
  description = "Public IP of VPN tunnel 1 (AWS side)."
  value       = aws_vpn_connection.tenant.tunnel1_address
}

output "vpn_tunnel2_address" {
  description = "Public IP of VPN tunnel 2 (AWS side)."
  value       = aws_vpn_connection.tenant.tunnel2_address
}

output "tenant_tgw_route_table_id" {
  description = "Per-tenant TGW route table ID (isolation)."
  value       = aws_ec2_transit_gateway_route_table.tenant.id
}

output "tenant_onprem_cidrs" {
  description = "On-prem CIDRs reachable through this tenant's VPN."
  value       = var.customer_onprem_cidrs
}
