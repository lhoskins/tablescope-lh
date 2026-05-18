# Tablescope — Terraform Deployment

Provisions an EC2 instance in AWS and automatically deploys the full Tablescope
Docker Compose stack (platform-api, web-ui, PostgreSQL, Redis, PgBouncer, worker).

## Prerequisites

- [Terraform](https://developer.hashicorp.com/terraform/downloads) >= 1.5
- AWS credentials with `AmazonEC2FullAccess` and `AmazonVPCFullAccess`

## Quick Start

```bash
cd terraform/

# Configure your deployment
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars — set vpc_id, subnet_id, key_name, etc.

# Export AWS credentials
export AWS_ACCESS_KEY_ID="AKIA..."
export AWS_SECRET_ACCESS_KEY="..."

# Deploy
terraform init
terraform plan        # review what will be created
terraform apply       # provision the instance

# Outputs will show the public IP, URLs, and SSH command
```

## What Gets Created

| Resource | Description |
|----------|-------------|
| EC2 instance | Ubuntu 22.04, t3.medium (configurable) |
| Security group | Ports 22, 3000, 8000, 8095, 35442 |
| SSH key pair | Auto-generated (or use existing) |

## What Runs on the Instance

The user-data script automatically:
1. Installs Docker + Docker Compose
2. Creates shared volume directories
3. Clones the repository
4. Generates `.env` with random secrets
5. Builds Docker images
6. Runs database migrations
7. Starts all services

## Checking Deployment Progress

```bash
# SSH into the instance
ssh -i tablescope-key.pem ubuntu@<public-ip>

# Watch the deployment log
tail -f /var/log/tablescope-deploy.log

# Check if deployment finished
cat ~/tablescope-ready.txt

# Check running services
cd ~/tablescope && docker compose ps
```

## Tear Down

```bash
terraform destroy
```

This removes the EC2 instance, security group, and key pair.
**All data on the instance will be lost.**
