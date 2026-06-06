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
  description = "Tablescope AI server — internal access only"
  vpc_id      = aws_vpc.ai.id

  # AI API (FastAPI) — from app server only
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
# IAM role — least privilege (self stop-instances + SSM)
# ---------------------------------------------------------------------------

resource "aws_iam_role" "ai_server" {
  name = "${var.instance_name}-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })

  tags = { Name = "${var.instance_name}-role" }
}

resource "aws_iam_role_policy" "self_stop" {
  name = "${var.instance_name}-self-stop"
  role = aws_iam_role.ai_server.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ec2:StopInstances", "ec2:DescribeInstances"]
        Resource = "*"
        Condition = {
          StringEquals = {
            "ec2:ResourceTag/Name" = var.instance_name
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.ai_server.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "ai_server" {
  name = "${var.instance_name}-profile"
  role = aws_iam_role.ai_server.name
}

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
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  key_name               = local.key_name
  subnet_id              = aws_subnet.private.id
  vpc_security_group_ids = [aws_security_group.ai_server.id]
  iam_instance_profile   = aws_iam_instance_profile.ai_server.name

  availability_zone           = var.availability_zone
  associate_public_ip_address = false

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
# ---------------------------------------------------------------------------

resource "aws_iam_role" "scheduler" {
  name = "${var.instance_name}-scheduler-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "scheduler_ec2" {
  name = "${var.instance_name}-scheduler-ec2"
  role = aws_iam_role.scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ec2:StartInstances", "ec2:StopInstances"]
      Resource = aws_instance.ai_server.arn
    }]
  })
}

resource "aws_scheduler_schedule" "start" {
  name       = "${var.instance_name}-start"
  group_name = "default"

  schedule_expression          = var.schedule_start_cron
  schedule_expression_timezone = "America/Los_Angeles"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = "arn:aws:scheduler:::aws-sdk:ec2:startInstances"
    role_arn = aws_iam_role.scheduler.arn

    input = jsonencode({
      InstanceIds = [aws_instance.ai_server.id]
    })
  }
}

resource "aws_scheduler_schedule" "stop" {
  name       = "${var.instance_name}-stop"
  group_name = "default"

  schedule_expression          = var.schedule_stop_cron
  schedule_expression_timezone = "America/Los_Angeles"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = "arn:aws:scheduler:::aws-sdk:ec2:stopInstances"
    role_arn = aws_iam_role.scheduler.arn

    input = jsonencode({
      InstanceIds = [aws_instance.ai_server.id]
    })
  }
}
