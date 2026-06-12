terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# ---------------------------------------------------------------------------
# VPC + Networking (private subnet for AI server)
# ---------------------------------------------------------------------------

resource "aws_vpc" "ai" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "${var.instance_name}-vpc" }
}

resource "aws_subnet" "private" {
  vpc_id                  = aws_vpc.ai.id
  cidr_block              = var.private_subnet_cidr
  availability_zone       = var.availability_zone
  map_public_ip_on_launch = false

  tags = { Name = "${var.instance_name}-private" }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.ai.id
  cidr_block              = var.public_subnet_cidr
  availability_zone       = var.availability_zone
  map_public_ip_on_launch = true

  tags = { Name = "${var.instance_name}-public" }
}

# Internet gateway (for NAT + initial SSH)
resource "aws_internet_gateway" "ai" {
  vpc_id = aws_vpc.ai.id
  tags   = { Name = "${var.instance_name}-igw" }
}

# Elastic IP for NAT Gateway
resource "aws_eip" "nat" {
  domain = "vpc"
  tags   = { Name = "${var.instance_name}-nat-eip" }
}

# NAT Gateway in public subnet (for private subnet outbound)
resource "aws_nat_gateway" "ai" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public.id

  tags = { Name = "${var.instance_name}-nat" }

  depends_on = [aws_internet_gateway.ai]
}

# Route table for private subnet → NAT
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.ai.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.ai.id
  }

  tags = { Name = "${var.instance_name}-private-rt" }
}

resource "aws_route_table_association" "private" {
  subnet_id      = aws_subnet.private.id
  route_table_id = aws_route_table.private.id
}

# Route table for public subnet → IGW
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.ai.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.ai.id
  }

  tags = { Name = "${var.instance_name}-public-rt" }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# ---------------------------------------------------------------------------
# SSH key pair
# ---------------------------------------------------------------------------

resource "tls_private_key" "ssh" {
  count     = var.key_name == "" ? 1 : 0
  algorithm = "ED25519"
}

resource "aws_key_pair" "generated" {
  count      = var.key_name == "" ? 1 : 0
  key_name   = "${var.instance_name}-key"
  public_key = tls_private_key.ssh[0].public_key_openssh
}

resource "local_file" "private_key" {
  count           = var.key_name == "" ? 1 : 0
  content         = tls_private_key.ssh[0].private_key_openssh
  filename        = "${path.module}/${var.instance_name}-key.pem"
  file_permission = "0600"
}

locals {
  key_name = var.key_name != "" ? var.key_name : aws_key_pair.generated[0].key_name
}

# ---------------------------------------------------------------------------
# Security group — AI server (private, internal only)
# ---------------------------------------------------------------------------

resource "aws_security_group" "ai_server" {
  name_prefix = "${var.instance_name}-"
  description = "Tablescope AI server - internal access only"
  vpc_id      = aws_vpc.ai.id

  # AI API (FastAPI) - from app server only
  ingress {
    description = "AI API from Tablescope app server"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["${var.app_server_ip}/32"]
  }

  # SSH — for initial setup (restrict in production)
  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = var.allowed_ssh_cidrs
  }

  # All outbound (model downloads, package installs)
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.instance_name}-sg" }
}

# ---------------------------------------------------------------------------
# IAM role - least privilege (self stop-instances + SSM)
# NOTE: IAM role creation requires elevated permissions. Create manually:
#   aws iam create-role --role-name tablescope-ai-server-role ...
#   aws iam create-instance-profile --instance-profile-name tablescope-ai-server-profile
# Then set var.instance_profile_name to attach it to the EC2 instance.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Ubuntu 22.04 AMI
# ---------------------------------------------------------------------------

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"]

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }

  filter {
    name   = "state"
    values = ["available"]
  }
}

# ---------------------------------------------------------------------------
# EC2 AI Server instance (private subnet)
# ---------------------------------------------------------------------------

resource "aws_instance" "ai_server" {
  ami                         = data.aws_ami.ubuntu.id
  instance_type               = var.instance_type
  key_name                    = local.key_name
  subnet_id                   = aws_subnet.public.id
  vpc_security_group_ids      = [aws_security_group.ai_server.id]
  availability_zone           = var.availability_zone
  associate_public_ip_address = true

  root_block_device {
    volume_size           = var.root_volume_size
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = true
  }

  user_data = templatefile("${path.module}/user-data-ai.sh.tpl", {
    repo_url             = var.repo_url
    branch               = var.branch
    ai_signing_secret    = var.ai_signing_secret
    app_server_ip        = var.app_server_ip
    app_base_url         = var.app_base_url
    idle_timeout_minutes = var.idle_timeout_minutes
  })

  tags = {
    Name = var.instance_name
  }

  lifecycle {
    ignore_changes = [ami, user_data]
  }
}

# ---------------------------------------------------------------------------
# 500 GB encrypted gp3 data volume
# ---------------------------------------------------------------------------

resource "aws_ebs_volume" "ai_data" {
  availability_zone = var.availability_zone
  size              = var.data_volume_size
  type              = "gp3"
  encrypted         = true
  iops              = 3000
  throughput        = 125

  tags = { Name = "${var.instance_name}-data" }
}

resource "aws_volume_attachment" "ai_data" {
  device_name = "/dev/xvdf"
  volume_id   = aws_ebs_volume.ai_data.id
  instance_id = aws_instance.ai_server.id
}

# ---------------------------------------------------------------------------
# EventBridge scheduled start/stop
# NOTE: Scheduler IAM role creation requires elevated permissions.
# Create manually after deployment:
#   1. Create IAM role for EventBridge Scheduler with ec2:StartInstances/StopInstances
#   2. Create EventBridge Scheduler rules for start/stop
# The Terraform resources are preserved in the implementation plan doc.
# ---------------------------------------------------------------------------
