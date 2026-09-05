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
  value       = try(aws_customer_gateway.tenant[0].id, null)
}

output "vpn_connection_id" {
  description = "Site-to-Site VPN connection ID."
  value       = try(aws_vpn_connection.tenant[0].id, null)
}

output "vpn_transit_gateway_attachment_id" {
  description = "TGW attachment ID of the tenant VPN connection."
  value       = try(aws_vpn_connection.tenant[0].transit_gateway_attachment_id, null)
}

output "vpn_tunnel1_address" {
  description = "Public IP of VPN tunnel 1 (AWS side)."
  value       = try(aws_vpn_connection.tenant[0].tunnel1_address, null)
}

output "vpn_tunnel2_address" {
  description = "Public IP of VPN tunnel 2 (AWS side)."
  value       = try(aws_vpn_connection.tenant[0].tunnel2_address, null)
}

output "tenant_tgw_route_table_id" {
  description = "Per-tenant TGW route table ID (isolation)."
  value       = aws_ec2_transit_gateway_route_table.tenant.id
}

output "tenant_onprem_cidrs" {
  description = "On-prem CIDRs reachable through this tenant's VPN."
  value       = var.customer_onprem_cidrs
}

output "storage" {
  description = "Non-secret metadata imported into the tenant data-plane registry."
  value = {
    s3_bucket_name      = aws_s3_bucket.tenant.id
    s3_region           = var.aws_region
    s3_prefix           = ""
    s3_access_point_arn = aws_s3_access_point.tenant.arn
    s3_vpc_endpoint_id  = aws_vpc_endpoint.s3.id
    s3_endpoint_url     = "https://${replace(aws_vpc_endpoint.s3.dns_entry[0].dns_name, "*.", "")}"
    s3_kms_key_arn      = aws_kms_key.storage.arn
    s3_role_arn         = aws_iam_role.storage.arn
    s3_force_private    = true
  }
}

output "storage_retained_by_default" {
  description = "Whether terraform destroy retains non-empty storage by default."
  value       = !var.storage_force_destroy
}
