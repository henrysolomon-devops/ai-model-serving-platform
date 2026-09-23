# Pinning the AWS provider version so this doesn't randomly break later
# if HashiCorp ships something incompatible in a newer release.
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  required_version = ">= 1.5.0"
}

# No access keys here on purpose. Terraform runs through GitHub Actions
# via OIDC (see infra.yml), so it picks up temporary credentials from
# the environment instead of anything stored in this repo.
provider "aws" {
  region = var.aws_region
}
