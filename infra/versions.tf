terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      # 6.67 is the version validated against: it has aws_bedrockagentcore_agent_runtime with
      # custom_jwt_authorizer, lifecycle_configuration and environment_variables.
      source  = "hashicorp/aws"
      version = "~> 6.67"
    }
  }

  # Partial config: terraform init -backend-config=backend.hcl (see backend.hcl.example).
  backend "s3" {}
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = var.project
      ManagedBy = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id

  # AgentCore runtime names allow only [a-zA-Z0-9_], start with a letter, max 48 chars.
  runtime_name   = "${replace(var.project, "-", "_")}_agent"
  create_runtime = var.image_tag != ""
}
