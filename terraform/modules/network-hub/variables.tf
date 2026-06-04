variable "amazon_side_asn" {
  description = "Private ASN for the Amazon side of the Transit Gateway."
  type        = number
  default     = 64512
}

variable "shared_vpc_id" {
  description = "ID of the shared services VPC that hosts the EC2 platform host."
  type        = string
}

variable "shared_subnet_ids" {
  description = "Subnet IDs (one per AZ) used for the shared services VPC TGW attachment."
  type        = list(string)
}

variable "shared_route_table_onprem_cidrs" {
  description = <<-EOT
    Map of route entries to add to the shared services VPC subnet route table(s),
    one per tenant on-prem CIDR, so the EC2 host routes that CIDR to the TGW.
    Keyed by an arbitrary unique string (e.g. "<tenant_id>-<idx>").
    Each value: { route_table_id = string, cidr = string }.
  EOT
  type = map(object({
    route_table_id = string
    cidr           = string
  }))
  default = {}
}
