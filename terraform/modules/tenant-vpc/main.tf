data "aws_caller_identity" "current" {}

locals {
  name_prefix      = "tablescope-tenant-${var.tenant_id}"
  safe_tenant       = substr(replace(lower(var.tenant_id), "/[^a-z0-9-]/", "-"), 0, 22)
  suffix           = substr(sha1(var.tenant_id), 0, 8)
  bucket_name      = coalesce(var.storage_bucket_name, "tablescope-${data.aws_caller_identity.current.account_id}-${local.safe_tenant}-${local.suffix}")
  access_point_name = substr("tablescope-${local.safe_tenant}-${local.suffix}", 0, 50)
  storage_role_name = "tablescope-tenant-${local.safe_tenant}-storage-${local.suffix}"
  storage_role_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.storage_role_name}"
  vpn_enabled      = var.vpn_mode == "customer_vpn"
  static_routes    = var.vpn_routing_type == "static"
  onprem_cidr_map  = { for idx, cidr in var.customer_onprem_cidrs : tostring(idx) => cidr }
}

resource "aws_vpc" "tenant" {
  cidr_block           = var.tenant_vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags = { Name = "${local.name_prefix}-vpc", Tenant = var.tenant_id, ManagedBy = "tablescope-tenant-dataplane" }
}

resource "aws_subnet" "tenant_private" {
  vpc_id            = aws_vpc.tenant.id
  cidr_block        = var.tenant_private_subnet_cidr
  availability_zone = var.availability_zone
  tags = { Name = "${local.name_prefix}-private", Tenant = var.tenant_id, ManagedBy = "tablescope-tenant-dataplane" }
}

resource "aws_route_table" "tenant" {
  vpc_id = aws_vpc.tenant.id
  tags   = { Name = "${local.name_prefix}-rt", Tenant = var.tenant_id, ManagedBy = "tablescope-tenant-dataplane" }
}

resource "aws_route_table_association" "tenant" {
  subnet_id      = aws_subnet.tenant_private.id
  route_table_id = aws_route_table.tenant.id
}

resource "aws_ec2_transit_gateway_vpc_attachment" "tenant" {
  subnet_ids                                      = [aws_subnet.tenant_private.id]
  transit_gateway_id                              = var.transit_gateway_id
  vpc_id                                          = aws_vpc.tenant.id
  transit_gateway_default_route_table_association = false
  transit_gateway_default_route_table_propagation = false
  tags = { Name = "${local.name_prefix}-tgw-attachment", Tenant = var.tenant_id }
}

resource "aws_route" "tenant_to_shared" {
  route_table_id         = aws_route_table.tenant.id
  destination_cidr_block = var.shared_vpc_cidr
  transit_gateway_id     = var.transit_gateway_id
}

resource "aws_security_group" "tenant" {
  name_prefix = "${local.name_prefix}-"
  description = "Tablescope tenant ${var.tenant_id} data-plane"
  vpc_id      = aws_vpc.tenant.id
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = { Name = "${local.name_prefix}-sg", Tenant = var.tenant_id, ManagedBy = "tablescope-tenant-dataplane" }
}

resource "aws_security_group" "s3_endpoint" {
  name_prefix = "${local.name_prefix}-s3-"
  description = "HTTPS from the shared runtime to tenant ${var.tenant_id} S3 endpoint"
  vpc_id      = aws_vpc.tenant.id
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.shared_vpc_cidr]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = { Name = "${local.name_prefix}-s3-endpoint", Tenant = var.tenant_id }
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id              = aws_vpc.tenant.id
  service_name        = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.tenant_private.id]
  security_group_ids  = [aws_security_group.s3_endpoint.id]
  private_dns_enabled = false
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = "*"
      Action    = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
      Resource  = [aws_s3_access_point.tenant.arn, "${aws_s3_access_point.tenant.arn}/object/*"]
      Condition = { StringEquals = { "aws:PrincipalArn" = local.storage_role_arn } }
    }]
  })
  tags = { Name = "${local.name_prefix}-s3", Tenant = var.tenant_id }
}

resource "aws_kms_key" "storage" {
  description             = "Tablescope tenant ${var.tenant_id} storage key"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  depends_on = [aws_iam_role.storage]
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AccountAdministration"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "TenantStorageRole"
        Effect    = "Allow"
        Principal = { AWS = local.storage_role_arn }
        Action    = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
        Resource  = "*"
        Condition = {
          StringEquals = { "kms:ViaService" = "s3.${var.aws_region}.amazonaws.com" }
          StringLike   = { "kms:EncryptionContext:aws:s3:arn" = "arn:aws:s3:::${local.bucket_name}/*" }
        }
      }
    ]
  })
  tags = { Name = "${local.name_prefix}-storage", Tenant = var.tenant_id }
}

resource "aws_kms_alias" "storage" {
  name          = "alias/${local.name_prefix}-storage-${local.suffix}"
  target_key_id = aws_kms_key.storage.key_id
}

resource "aws_s3_bucket" "tenant" {
  bucket        = local.bucket_name
  force_destroy = var.storage_force_destroy
  tags = { Name = local.bucket_name, Tenant = var.tenant_id, DataClassification = "customer", ManagedBy = "tablescope-tenant-dataplane" }
}

resource "aws_s3_bucket_versioning" "tenant" {
  bucket = aws_s3_bucket.tenant.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tenant" {
  bucket = aws_s3_bucket.tenant.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.storage.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "tenant" {
  bucket                  = aws_s3_bucket.tenant.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_access_point" "tenant" {
  bucket = aws_s3_bucket.tenant.id
  name   = local.access_point_name
  vpc_configuration { vpc_id = aws_vpc.tenant.id }
}

resource "aws_s3control_access_point_policy" "tenant" {
  access_point_arn = aws_s3_access_point.tenant.arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { AWS = aws_iam_role.storage.arn }
      Action    = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
      Resource  = [aws_s3_access_point.tenant.arn, "${aws_s3_access_point.tenant.arn}/object/*"]
    }]
  })
}

resource "aws_iam_role" "storage" {
  name = local.storage_role_name
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { AWS = var.runtime_principal_arn }
      Action    = "sts:AssumeRole"
    }]
  })
  tags = { Tenant = var.tenant_id, ManagedBy = "tablescope-tenant-dataplane" }
}

resource "aws_iam_role_policy" "storage" {
  name = "private-s3-boundary"
  role = aws_iam_role.storage.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = "${aws_s3_access_point.tenant.arn}/object/*"
      },
      {
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = aws_s3_access_point.tenant.arn
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
        Resource = aws_kms_key.storage.arn
      }
    ]
  })
}

resource "aws_s3_bucket_policy" "tenant" {
  bucket = aws_s3_bucket.tenant.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DelegateOnlyThroughTenantAccessPoint"
        Effect    = "Allow"
        Principal = { AWS = aws_iam_role.storage.arn }
        Action    = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
        Resource  = [aws_s3_bucket.tenant.arn, "${aws_s3_bucket.tenant.arn}/*"]
        Condition = {
          StringEquals = {
            "aws:SourceVpce"       = aws_vpc_endpoint.s3.id
            "s3:DataAccessPointArn" = aws_s3_access_point.tenant.arn
          }
        }
      },
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = [aws_s3_bucket.tenant.arn, "${aws_s3_bucket.tenant.arn}/*"]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      },
      {
        Sid       = "DenyOutsideTenantEndpoint"
        Effect    = "Deny"
        Principal = "*"
        Action    = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
        Resource  = [aws_s3_bucket.tenant.arn, "${aws_s3_bucket.tenant.arn}/*"]
        Condition = { StringNotEquals = { "aws:SourceVpce" = aws_vpc_endpoint.s3.id } }
      },
      {
        Sid       = "DenyDirectBucketAccess"
        Effect    = "Deny"
        Principal = "*"
        Action    = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
        Resource  = [aws_s3_bucket.tenant.arn, "${aws_s3_bucket.tenant.arn}/*"]
        Condition = { StringNotEquals = { "s3:DataAccessPointArn" = aws_s3_access_point.tenant.arn } }
      },
      {
        Sid       = "DenyWrongEncryptionAlgorithm"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.tenant.arn}/*"
        Condition = { StringNotEquals = { "s3:x-amz-server-side-encryption" = "aws:kms" } }
      },
      {
        Sid       = "DenyWrongKmsKey"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.tenant.arn}/*"
        Condition = { StringNotEquals = { "s3:x-amz-server-side-encryption-aws-kms-key-id" = aws_kms_key.storage.arn } }
      }
    ]
  })
  depends_on = [aws_s3_bucket_public_access_block.tenant]
}

resource "aws_customer_gateway" "tenant" {
  count      = local.vpn_enabled ? 1 : 0
  bgp_asn    = var.customer_bgp_asn
  ip_address = var.customer_gateway_ip
  type       = "ipsec.1"
  tags = { Name = "${local.name_prefix}-cgw", Tenant = var.tenant_id, ManagedBy = "tablescope-tenant-dataplane" }
}

resource "aws_vpn_connection" "tenant" {
  count               = local.vpn_enabled ? 1 : 0
  customer_gateway_id = aws_customer_gateway.tenant[0].id
  transit_gateway_id  = var.transit_gateway_id
  type                = "ipsec.1"
  static_routes_only  = local.static_routes
  tags = { Name = "${local.name_prefix}-vpn", Tenant = var.tenant_id, ManagedBy = "tablescope-tenant-dataplane" }
}

resource "aws_vpn_connection_route" "tenant" {
  for_each               = local.vpn_enabled && local.static_routes ? local.onprem_cidr_map : {}
  destination_cidr_block = each.value
  vpn_connection_id      = aws_vpn_connection.tenant[0].id
}

resource "aws_ec2_transit_gateway_route_table" "tenant" {
  transit_gateway_id = var.transit_gateway_id
  tags = { Name = "${local.name_prefix}-tgw-rt", Tenant = var.tenant_id, ManagedBy = "tablescope-tenant-dataplane" }
}

resource "aws_ec2_transit_gateway_route_table_association" "tenant_vpc" {
  transit_gateway_attachment_id  = aws_ec2_transit_gateway_vpc_attachment.tenant.id
  transit_gateway_route_table_id = aws_ec2_transit_gateway_route_table.tenant.id
}

resource "aws_ec2_transit_gateway_route_table_association" "tenant_vpn" {
  count                          = local.vpn_enabled ? 1 : 0
  transit_gateway_attachment_id  = aws_vpn_connection.tenant[0].transit_gateway_attachment_id
  transit_gateway_route_table_id = aws_ec2_transit_gateway_route_table.tenant.id
}

resource "aws_ec2_transit_gateway_route" "tenant_to_shared" {
  destination_cidr_block         = var.shared_vpc_cidr
  transit_gateway_attachment_id  = var.shared_attachment_id
  transit_gateway_route_table_id = aws_ec2_transit_gateway_route_table.tenant.id
}

resource "aws_ec2_transit_gateway_route" "shared_to_tenant_vpc" {
  destination_cidr_block         = var.tenant_vpc_cidr
  transit_gateway_attachment_id  = aws_ec2_transit_gateway_vpc_attachment.tenant.id
  transit_gateway_route_table_id = var.shared_route_table_id
}

resource "aws_ec2_transit_gateway_route" "shared_to_onprem" {
  for_each = local.vpn_enabled ? local.onprem_cidr_map : {}
  destination_cidr_block         = each.value
  transit_gateway_attachment_id  = aws_vpn_connection.tenant[0].transit_gateway_attachment_id
  transit_gateway_route_table_id = var.shared_route_table_id
}
