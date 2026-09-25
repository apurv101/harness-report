terraform {
  required_version = ">= 1.11"

  required_providers {
    aws     = { source = "hashicorp/aws", version = ">= 5.70" }
    archive = { source = "hashicorp/archive", version = "~> 2.4" }
    random  = { source = "hashicorp/random", version = "~> 3.6" }
  }
}

# Credentials come from the environment: AWS_PROFILE=operator locally, the OIDC role in CI.
# Nothing here names a profile, so the same files apply from either side.
provider "aws" {
  region = var.region
  default_tags { tags = local.tags }
}

# CloudFront reads its certificate out of us-east-1 wherever the rest of the stack lives.
provider "aws" {
  alias  = "acm"
  region = "us-east-1"
  default_tags { tags = local.tags }
}
