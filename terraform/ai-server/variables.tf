variable "aws_region" {
  description = "AWS region for the AI server"
  type        = string
  default     = "us-west-2"
}

variable "availability_zone" {
  description = "Availability zone for the AI server"
  type        = string
  default     = "us-west-2a"
}

variable "instance_type" {
  description = "GPU instance type for the AI server"
  type        = string
  default     = "g6.xlarge"
}

variable "root_volume_size" {
  description = "Root EBS volume size in GB"
  type        = number
  default     = 100
}

variable "data_volume_size" {
  description = "Data EBS volume size in GB (mounted at /mnt/tablescope-ai)"
  type        = number
  default     = 500
}

variable "vpc_cidr" {
  description = "CIDR block for the AI server VPC"
  type        = string
  default     = "10.200.0.0/16"
}

variable "private_subnet_cidr" {
  description = "CIDR block for the private subnet"
  type        = string
  default     = "10.200.1.0/24"
}

variable "public_subnet_cidr" {
  description = "CIDR block for the public subnet (NAT gateway)"
  type        = string
  default     = "10.200.2.0/24"
}

variable "instance_name" {
  description = "Name tag for the AI server"
  type        = string
  default     = "tablescope-ai-server"
}

variable "app_server_ip" {
  description = "Public IP of the Tablescope app server (for security group rules)"
  type        = string
  default     = "13.57.117.13"
}

variable "app_base_url" {
  description = "Base URL of the platform-api as reached by the AI server. Use the public HTTPS endpoint (nginx-proxied); the raw :8000 port is firewalled off."
  type        = string
  default     = "https://app.tablescope.cloud"
}

variable "key_name" {
  description = "Existing EC2 key pair name (leave empty to generate new)"
  type        = string
  default     = ""
}

variable "repo_url" {
  description = "Git repository URL"
  type        = string
  default     = "https://github.com/lhoskins/tablescope-lh.git"
}

variable "branch" {
  description = "Git branch to deploy"
  type        = string
  default     = "devin/1780704471-ai-server-implementation"
}

variable "ai_signing_secret" {
  description = "HMAC signing secret shared between app server and AI server"
  type        = string
  sensitive   = true
  default     = ""
}

variable "schedule_start_cron" {
  description = "EventBridge cron for starting the AI server (UTC)"
  type        = string
  default     = "cron(0 15 ? * MON-FRI *)" # 8 AM PT
}

variable "schedule_stop_cron" {
  description = "EventBridge cron for stopping the AI server (UTC)"
  type        = string
  default     = "cron(0 1 ? * TUE-SAT *)" # 6 PM PT
}

variable "idle_timeout_minutes" {
  description = "Minutes of inactivity before auto-stop"
  type        = number
  default     = 60
}

variable "allowed_ssh_cidrs" {
  description = "CIDR blocks allowed to SSH (for initial setup only)"
  type        = list(string)
  default     = ["0.0.0.0/0"]
}
