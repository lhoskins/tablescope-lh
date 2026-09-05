variable "tenant_id" {
  description = "Stable tenant identifier (lowercase, e.g. \"acme\")."
  type        = string
}

variable "availability_zone" {
  description = "AZ for the tenant private subnet."
  type        = string
}

variable "tenant_vpc_cidr" {
  description = "CIDR block for the tenant VPC (must not overlap other tenants or the shared VPC)."
  type        = string
}

variable "tenant_private_subnet_cidr" {
  description = "CIDR block for the tenant private subnet (within the tenant VPC CIDR)."
  type        = string
}

variable "customer_gateway_ip" {
  description = "Public IPv4 of the customer's on-prem VPN device (customer gateway)."
  type        = string
  default     = null
  nullable    = true
}

variable "vpn_mode" {
  description = "none or customer_vpn"
  type        = string
  default     = "none"
  validation {
    condition     = contains(["none", "customer_vpn"], var.vpn_mode)
    error_message = "vpn_mode must be none or customer_vpn."
  }
}

variable "customer_bgp_asn" {
  description = "BGP ASN for the customer gateway (only used when vpn_routing_type = \"bgp\")."
  type        = number
  default     = 65000
}

variable "customer_onprem_cidrs" {
  description = "List of on-prem CIDR(s) reachable behind the customer VPN. Must not overlap other tenants for MVP."
  type        = list(string)
}

variable "vpn_routing_type" {
  description = "\"static\" (default) or \"bgp\"."
  type        = string
  default     = "static"

  validation {
    condition     = contains(["static", "bgp"], var.vpn_routing_type)
    error_message = "vpn_routing_type must be \"static\" or \"bgp\"."
  }
}

variable "transit_gateway_id" {
  description = "ID of the shared Transit Gateway (from the network-hub module)."
  type        = string
}

variable "shared_attachment_id" {
  description = "TGW attachment ID of the shared services VPC (from the network-hub module)."
  type        = string
}

variable "shared_route_table_id" {
  description = "TGW route table associated with the shared services VPC attachment (from the network-hub module)."
  type        = string
}

variable "shared_vpc_cidr" {
  description = "CIDR block of the shared services VPC (for the VPN return route)."
  type        = string
}

variable "aws_region" {
  description = "AWS region used for the S3 endpoint and KMS service condition."
  type        = string
}

variable "runtime_principal_arn" {
  description = "Only principal allowed to assume this tenant's storage role."
  type        = string
}

variable "storage_bucket_name" {
  description = "Optional globally unique bucket name; generated when null."
  type        = string
  default     = null
  nullable    = true
}

variable "storage_force_destroy" {
  description = "Delete objects on destroy. Keep false in production for retention."
  type        = bool
  default     = false
}
