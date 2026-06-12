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
# Data sources – look up existing infrastructure
# ---------------------------------------------------------------------------

data "aws_vpc" "selected" {
  id = var.vpc_id != "" ? var.vpc_id : null

  dynamic "filter" {
    for_each = var.vpc_id == "" ? [1] : []
    content {
      name   = "is-default"
      values = ["true"]
    }
  }
}

data "aws_subnet" "selected" {
  count = var.subnet_id != "" ? 0 : 1

  vpc_id            = data.aws_vpc.selected.id
  availability_zone = var.availability_zone

  filter {
    name   = "map-public-ip-on-launch"
    values = ["true"]
  }
}

locals {
  subnet_id = var.subnet_id != "" ? var.subnet_id : data.aws_subnet.selected[0].id
}

# Latest Ubuntu 22.04 AMI (Canonical)
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

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
# SSH key pair – use existing or generate new
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
# Security group
# ---------------------------------------------------------------------------

resource "aws_security_group" "tablescope" {
  name_prefix = "${var.instance_name}-"
  description = "Tablescope application security group"
  vpc_id      = data.aws_vpc.selected.id

  # SSH
  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = var.allowed_ssh_cidrs
  }

  # HTTP — Let's Encrypt ACME challenge + redirect to HTTPS
  ingress {
    description = "HTTP (ACME + HTTPS redirect)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # HTTPS — nginx reverse proxy in front of the web UI
  ingress {
    description = "HTTPS (nginx reverse proxy)"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Web UI (Next.js)
  ingress {
    description = "Web UI"
    from_port   = 3000
    to_port     = 3000
    protocol    = "tcp"
    cidr_blocks = var.allowed_app_cidrs
  }

  # Platform API (FastAPI)
  ingress {
    description = "Platform API"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = var.allowed_app_cidrs
  }

  # Teiid PG wire protocol
  ingress {
    description = "Teiid PG wire"
    from_port   = 35442
    to_port     = 35442
    protocol    = "tcp"
    cidr_blocks = var.allowed_app_cidrs
  }

  # Teiid servlet
  ingress {
    description = "Teiid servlet"
    from_port   = 8095
    to_port     = 8095
    protocol    = "tcp"
    cidr_blocks = var.allowed_app_cidrs
  }

  # WildFly management console
  ingress {
    description = "WildFly management"
    from_port   = 9990
    to_port     = 9990
    protocol    = "tcp"
    cidr_blocks = var.allowed_app_cidrs
  }

  # All outbound
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.instance_name}-sg"
  }
}

# ---------------------------------------------------------------------------
# EC2 instance
# ---------------------------------------------------------------------------

resource "aws_instance" "tablescope" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  key_name               = local.key_name
  subnet_id              = local.subnet_id
  vpc_security_group_ids = [aws_security_group.tablescope.id]

  availability_zone           = var.availability_zone
  associate_public_ip_address = true

  root_block_device {
    volume_size           = var.volume_size
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = true
  }

  user_data = templatefile("${path.module}/user-data.sh.tpl", {
    repo_url = var.repo_url
    branch   = var.branch
  })

  tags = {
    Name = var.instance_name
  }

  lifecycle {
    ignore_changes = [ami, user_data]
  }
}
