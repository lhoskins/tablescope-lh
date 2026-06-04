output "transit_gateway_id" {
  description = "ID of the shared Transit Gateway."
  value       = aws_ec2_transit_gateway.hub.id
}

output "shared_attachment_id" {
  description = "TGW attachment ID for the shared services VPC."
  value       = aws_ec2_transit_gateway_vpc_attachment.shared.id
}

output "shared_route_table_id" {
  description = "TGW route table associated with the shared services VPC attachment."
  value       = aws_ec2_transit_gateway_route_table.shared.id
}
