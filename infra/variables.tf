variable "region" {
  description = "Where everything but the CloudFront certificate lives."
  type        = string
  default     = "us-west-2"
}

variable "project" {
  description = "Name prefix for every resource."
  type        = string
  default     = "harness-report"
}

variable "domain" {
  description = "The apex domain.  Its Route 53 zone must already exist in this account."
  type        = string
  default     = "harnessreport.com"
}

variable "github_repo" {
  description = "owner/name of the repository CI deploys from."
  type        = string
  default     = "apurv101/harness-report"
}

variable "github_repo_ids" {
  description = <<-EOT
    The same repository written as GitHub's *immutable* OIDC subject: owner@<owner_id>/repo@<repo_id>.
    GitHub now issues subject claims in this form so that renaming a repository — or someone else
    later claiming the freed name — cannot silently satisfy a trust policy.  Both forms are trusted
    because which one arrives depends on the account's setting, and AWS matches the literal string.
    Read them from `gh api /repos/<owner>/<name> --jq '.owner.id, .id'`.  Empty trusts only the
    classic form.
  EOT
  type        = string
  default     = "apurv101@14235444/harness-report@1382886271"
}

variable "create_oidc_provider" {
  description = <<-EOT
    Create the GitHub OIDC provider.  One per account: leave it true for the first stack in an
    account, false if something else already registered token.actions.githubusercontent.com.
  EOT
  type        = bool
  default     = true
}

variable "table_name" {
  description = "The run store.  Must match HR_TABLE in .env so the laptop and the site read one table."
  type        = string
  default     = "harness-report"
}

# The GitHub App's public half (github.com/apps/harness-report).  These are identifiers, not
# secrets — the client id travels in the browser's address bar on every sign-in — so they are
# defaults here rather than in a tfvars file.  That is not cosmetic: terraform.tfvars is gitignored,
# so anything that lives only there is absent in CI, and the first green deploy wiped both of these
# off the Lambda and turned sign-in off on the live site.  Whatever CI needs belongs in a file CI
# gets.  The client secret and the .pem are SecureStrings in SSM and are not Terraform's business
# at all (api.tf).
variable "github_client_id" {
  description = "GitHub App client id (Iv23li...).  Empty leaves sign-in off and the site read-only."
  type        = string
  default     = "Iv23liOJniEBUs74yCMX"
}

variable "github_app_id" {
  description = "GitHub App numeric id.  Only needed to mint clone tokens for private repositories."
  type        = string
  default     = "5064982"
}

variable "github_app_slug" {
  description = "GitHub App url slug, so the frontend can offer \"install it on a repository\"."
  type        = string
  default     = "harness-report"
}

variable "allow_data_destroy" {
  description = <<-EOT
    Let `terraform destroy` empty and delete the runs and recipes buckets.  False everywhere but the
    destroy workflow, which passes it on the command line, so the buckets that hold real output can
    never go away as a side effect of an ordinary apply.
  EOT
  type        = bool
  default     = false
}

variable "lambda_memory_mb" {
  description = "serve.py is I/O bound on DynamoDB; memory buys CPU for JSON, not much else."
  type        = number
  default     = 512
}

variable "lambda_timeout_s" {
  description = "A run bundle with 1,000 calls is the slow path.  CloudFront gives up at 30 s anyway."
  type        = number
  default     = 30
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "price_class" {
  description = "PriceClass_100 is North America + Europe.  PriceClass_All adds the rest at a higher rate."
  type        = string
  default     = "PriceClass_100"
}

# ---------------------------------------------------------------- the run plane

variable "enable_run_plane" {
  description = <<-EOT
    Provision demand-driven workers and their release/task bucket. Enable runner_dispatch_enabled
    after uploading tasks and migrating legacy jobs. Each VM runs one evaluation and retires.
  EOT
  type        = bool
  default     = false
}

variable "runner_instance_type" {
  description = "x86 evaluation host; Docker caches use EBS so a stopped warm worker retains them."
  type        = string
  default     = "c6i.2xlarge"
}

variable "runner_warm_pool" {
  description = "Unused stopped workers to maintain and replenish in the background. Zero disables standby; idle workers never stay running."
  type        = number
  default     = 2
}

variable "runner_max_size" {
  description = "Maximum simultaneous evaluation VMs; demand determines the actual running capacity."
  type        = number
  default     = 4
}

variable "runner_dispatch_enabled" {
  description = "Accept automatic fleet wakeups after tasks and migration are ready. Disabled also disables standby preparation."
  type        = bool
  default     = false
}

variable "runner_ami_id" {
  description = "Prepared Ubuntu AMI built with infra/runner-image.pkr.hcl in this account/us-west-2. Override for another account/region; empty installs dependencies during first warm-up."
  type        = string
  default     = "ami-07b3adfc7d225a1ea"
}

variable "runner_disk_gb" {
  description = "Encrypted EBS root including reusable Docker layers, preserved while an unused worker is stopped."
  type        = number
  default     = 200
}

variable "runner_model" {
  description = "Default Bedrock route for the evaluation proxy."
  type        = string
  default     = "bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0"
}

variable "runner_analyzer_model" {
  description = "Bedrock inference profile used by the Claude CLI for uncached recipes."
  type        = string
  default     = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
}

variable "runner_max_job_seconds" {
  description = "Maximum time for one evaluation, including preparation and verification."
  type        = number
  default     = 7200
  validation {
    condition     = var.runner_max_job_seconds >= 60 && var.runner_max_job_seconds <= 39600
    error_message = "Job time must be between 60 seconds and 11 hours (below SQS's 12-hour visibility ceiling)."
  }
}
