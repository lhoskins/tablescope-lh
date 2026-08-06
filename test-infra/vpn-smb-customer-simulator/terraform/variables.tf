variable "aws_region" {
  description = "AWS region for the simulator"
  type        = string
  default     = "us-west-1"
}

variable "environment" {
  description = "Environment tag"
  type        = string
  default     = "e2e"
}

variable "run_id" {
  description = "Unique run id for this test (used in names and tags)"
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR for the simulated customer VPC. Must not overlap TableScope tenant Docker subnets or other test VPCs."
  type        = string
  default     = "10.250.0.0/16"
}

variable "public_subnet_cidr" {
  description = "Public subnet for the VPN gateway host"
  type        = string
  default     = "10.250.10.0/24"
}

variable "availability_zone" {
  description = "AZ for the simulator subnet"
  type        = string
  default     = "us-west-1a"
}

variable "instance_type" {
  description = "EC2 instance type for the VPN gateway"
  type        = string
  default     = "t3.micro"
}

variable "allowed_vpn_cidrs" {
  description = "CIDR blocks allowed to send IKE/IPsec to the customer gateway. Tighten after AWS VPN tunnel IPs are known."
  type        = list(string)
  default     = []
}

variable "key_pair_name" {
  description = "Optional EC2 key pair name for debugging"
  type        = string
  default     = ""
}

variable "auto_cleanup" {
  description = "Expected cleanup time (e.g. '+4 hours')"
  type        = string
  default     = "+4 hours"
}
