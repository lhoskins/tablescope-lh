output "instance_id" {
  description = "AI server EC2 instance ID"
  value       = aws_instance.ai_server.id
}

output "private_ip" {
  description = "Private IP of the AI server"
  value       = aws_instance.ai_server.private_ip
}

output "ai_api_url" {
  description = "AI API URL (accessible from app server only)"
  value       = "http://${aws_instance.ai_server.private_ip}:8000"
}

output "security_group_id" {
  description = "AI server security group ID"
  value       = aws_security_group.ai_server.id
}

output "data_volume_id" {
  description = "500 GB encrypted data EBS volume ID"
  value       = aws_ebs_volume.ai_data.id
}

output "vpc_id" {
  description = "AI server VPC ID"
  value       = aws_vpc.ai.id
}

output "nat_gateway_ip" {
  description = "NAT gateway public IP (for outbound traffic)"
  value       = aws_eip.nat.public_ip
}

output "ssh_command" {
  description = "SSH command (via bastion or SSM)"
  value       = "aws ssm start-session --target ${aws_instance.ai_server.id} --region ${var.aws_region}"
}

output "ssh_key_file" {
  description = "Path to generated SSH key (if new key was created)"
  value       = var.key_name == "" ? "${path.module}/${var.instance_name}-key.pem" : "N/A — using existing key: ${var.key_name}"
}

output "schedule_start" {
  description = "Scheduled start time"
  value       = var.schedule_start_cron
}

output "schedule_stop" {
  description = "Scheduled stop time"
  value       = var.schedule_stop_cron
}
