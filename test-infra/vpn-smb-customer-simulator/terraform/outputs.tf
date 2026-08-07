output "customer_gateway_public_ip" {
  description = "Elastic IP of the simulated customer gateway. Use this as customer_gateway_ip in TableScope tenant Terraform."
  value       = aws_eip.gateway.public_ip
}

output "customer_lan_cidr" {
  description = "CIDR of the simulated customer LAN"
  value       = var.public_subnet_cidr
}

output "simulator_instance_id" {
  description = "EC2 instance id of the customer gateway"
  value       = aws_instance.gateway.id
}

output "simulator_vpc_id" {
  description = "VPC id of the simulator"
  value       = aws_vpc.customer.id
}

output "samba_private_ip" {
  description = "Private IP the Samba container will use on the internal Docker bridge"
  value       = "10.250.20.20"
}
