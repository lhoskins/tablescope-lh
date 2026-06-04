variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "us-west-1"
}

variable "availability_zone" {
  description = "Availability zone for the EC2 instance"
  type        = string
  default     = "us-west-1a"
}

variable "instance_type" {
  description = "EC2 instance type (t3.medium recommended minimum for Docker workloads)"
  type        = string
  default     = "t3.medium"
}

variable "volume_size" {
  description = "Root EBS volume size in GB"
  type        = number
  default     = 30
}

variable "vpc_id" {
  description = "Existing VPC ID (leave empty to use the default VPC)"
  type        = string
  default     = ""
}

variable "subnet_id" {
  description = "Existing subnet ID (leave empty to auto-select a public subnet in the AZ)"
  type        = string
  default     = ""
}

variable "key_name" {
  description = "Existing EC2 key pair name for SSH access (leave empty to generate a new one)"
  type        = string
  default     = ""
}

variable "repo_url" {
  description = "Git repository URL for tablescope"
  type        = string
  default     = "https://github.com/lhoskins/tablescope-lh.git"
}

variable "branch" {
  description = "Git branch to deploy"
  type        = string
  default     = "feature/multi-tenant-platform-migration"
}

variable "instance_name" {
  description = "Name tag for the EC2 instance"
  type        = string
  default     = "tablescope"
}

variable "allowed_ssh_cidrs" {
  description = "CIDR blocks allowed to SSH (port 22). Default allows all; restrict for production."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "allowed_app_cidrs" {
  description = "CIDR blocks allowed to access the application (ports 3000, 8000). Default allows all."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}
