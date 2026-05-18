output "instance_id" {
  description = "EC2 instance ID"
  value       = aws_instance.tablescope.id
}

output "public_ip" {
  description = "Public IP address of the instance"
  value       = aws_instance.tablescope.public_ip
}

output "web_ui_url" {
  description = "URL for the Tablescope web UI"
  value       = "http://${aws_instance.tablescope.public_ip}:3000"
}

output "platform_api_url" {
  description = "URL for the Tablescope platform API"
  value       = "http://${aws_instance.tablescope.public_ip}:8000"
}

output "platform_api_health" {
  description = "Health check URL"
  value       = "http://${aws_instance.tablescope.public_ip}:8000/health/live"
}

output "ssh_command" {
  description = "SSH command to connect to the instance"
  value       = var.key_name != "" ? "ssh -i <your-key.pem> ubuntu@${aws_instance.tablescope.public_ip}" : "ssh -i ${path.module}/${var.instance_name}-key.pem ubuntu@${aws_instance.tablescope.public_ip}"
}

output "ssh_private_key_file" {
  description = "Path to the generated SSH private key (if a new key was generated)"
  value       = var.key_name == "" ? "${path.module}/${var.instance_name}-key.pem" : "N/A — using existing key: ${var.key_name}"
}

output "security_group_id" {
  description = "Security group ID"
  value       = aws_security_group.tablescope.id
}

output "deploy_log" {
  description = "Command to check deployment progress on the instance"
  value       = "ssh ubuntu@${aws_instance.tablescope.public_ip} 'tail -f /var/log/tablescope-deploy.log'"
}
