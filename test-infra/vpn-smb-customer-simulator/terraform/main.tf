# ---------------------------------------------------------------------------
# Simulated customer environment for TableScope VPN/SMB E2E validation.
#
# This creates an isolated VPC with a single EC2 instance that runs:
#   * strongSwan as the customer VPN gateway (host networking, public EIP)
#   * Samba as the repository backend (container on a private Docker bridge)
#
# The SMB share is reachable only from the simulated customer LAN and from
# the IPsec tunnel terminated on the gateway host.
# ---------------------------------------------------------------------------

locals {
  name_prefix = "tablescope-vpn-smb-e2e-${var.run_id}"
}

# --- Networking --------------------------------------------------------------

resource "aws_vpc" "customer" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = "${local.name_prefix}-vpc"
  }
}

resource "aws_internet_gateway" "customer" {
  vpc_id = aws_vpc.customer.id

  tags = {
    Name = "${local.name_prefix}-igw"
  }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.customer.id
  cidr_block              = var.public_subnet_cidr
  availability_zone       = var.availability_zone
  map_public_ip_on_launch = false

  tags = {
    Name = "${local.name_prefix}-public"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.customer.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.customer.id
  }

  tags = {
    Name = "${local.name_prefix}-public-rt"
  }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# --- Security groups ---------------------------------------------------------

resource "aws_security_group" "gateway" {
  name_prefix = "${local.name_prefix}-gw-"
  description = "Allow IKE/IPsec to the customer gateway"
  vpc_id      = aws_vpc.customer.id

  dynamic "ingress" {
    for_each = var.allowed_vpn_cidrs
    content {
      description = "IKE from AWS tunnel endpoint"
      from_port   = 500
      to_port     = 500
      protocol    = "udp"
      cidr_blocks = [ingress.value]
    }
  }

  dynamic "ingress" {
    for_each = var.allowed_vpn_cidrs
    content {
      description = "NAT-T from AWS tunnel endpoint"
      from_port   = 4500
      to_port     = 4500
      protocol    = "udp"
      cidr_blocks = [ingress.value]
    }
  }

  dynamic "ingress" {
    for_each = var.allowed_vpn_cidrs
    content {
      description = "ESP from AWS tunnel endpoint"
      protocol    = "esp"
      from_port   = 0
      to_port     = 0
      cidr_blocks = [ingress.value]
    }
  }

  # SSH for emergency debugging only; restrict in production.
  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${local.name_prefix}-gateway-sg"
  }
}

resource "aws_security_group" "smb_internal" {
  name_prefix = "${local.name_prefix}-smb-"
  description = "SMB3 only from the customer LAN"
  vpc_id      = aws_vpc.customer.id

  ingress {
    description = "SMB3 TCP"
    from_port   = 445
    to_port     = 445
    protocol    = "tcp"
    cidr_blocks = [var.public_subnet_cidr]
  }

  egress {
    description = "No outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = []
  }

  tags = {
    Name = "${local.name_prefix}-smb-sg"
  }
}

# --- IAM ----------------------------------------------------------------------

resource "aws_iam_role" "gateway" {
  name = "${local.name_prefix}-gateway-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.gateway.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "gateway" {
  name = "${local.name_prefix}-gateway-profile"
  role = aws_iam_role.gateway.name
}

# --- EC2 ---------------------------------------------------------------------

data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }
}

resource "aws_instance" "gateway" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.gateway.id]
  iam_instance_profile   = aws_iam_instance_profile.gateway.name
  source_dest_check      = false
  key_name               = var.key_pair_name != "" ? var.key_pair_name : null

  user_data = file("${path.module}/../scripts/gateway-user-data.sh")

  root_block_device {
    volume_size           = 20
    encrypted             = true
    delete_on_termination = true
  }

  tags = {
    Name = "${local.name_prefix}-gateway"
  }
}

resource "aws_eip" "gateway" {
  instance = aws_instance.gateway.id
  domain   = "vpc"

  depends_on = [aws_internet_gateway.customer]

  tags = {
    Name = "${local.name_prefix}-gateway-eip"
  }
}

# --- Flow logs ---------------------------------------------------------------

resource "aws_flow_log" "customer" {
  vpc_id                   = aws_vpc.customer.id
  traffic_type             = "ALL"
  log_destination_type     = "cloud-watch-logs"
  log_destination          = aws_cloudwatch_log_group.flow_logs.arn
  iam_role_arn             = aws_iam_role.flow_logs.arn
  max_aggregation_interval = 60
}

resource "aws_cloudwatch_log_group" "flow_logs" {
  name              = "/aws/vpc/flowlogs/${local.name_prefix}"
  retention_in_days = 1
}

resource "aws_iam_role" "flow_logs" {
  name = "${local.name_prefix}-flowlogs-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "vpc-flow-logs.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "flow_logs" {
  name = "${local.name_prefix}-flowlogs-policy"
  role = aws_iam_role.flow_logs.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
      Resource = "${aws_cloudwatch_log_group.flow_logs.arn}:*"
    }]
  })
}
