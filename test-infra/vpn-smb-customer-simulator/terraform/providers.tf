terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Name        = "tablescope-vpn-smb-e2e-${var.run_id}"
      ManagedBy   = "tablescope-vpn-smb-e2e"
      RunId       = var.run_id
      Environment = var.environment
      AutoCleanup = var.auto_cleanup
    }
  }
}
