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

# The GitHub App's public half.  The client secret and the .pem are SecureStrings in SSM, never here.
variable "github_client_id" {
  description = "GitHub App client id (Iv23li...).  Empty leaves sign-in off and the site read-only."
  type        = string
  default     = ""
}

variable "github_app_id" {
  description = "GitHub App numeric id.  Only needed to mint clone tokens for private repositories."
  type        = string
  default     = ""
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
    Turn on the EC2 runner fleet from RUN-PLANE.md: SQS, the launch template and a warm pool.
    Off by default because hr-agentd — the daemon that leases from the queue and calls run.sh —
    does not exist yet, so a fleet turned on now is a bill with nothing to do.
  EOT
  type        = bool
  default     = false
}

variable "runner_instance_type" {
  description = "x86 with instance-store NVMe: the Harbor corpus is amd64 and image unpack is disk-bound."
  type        = string
  default     = "c6id.2xlarge"
}

variable "runner_warm_pool" {
  description = "Instances kept booted and tagged hr:state=free.  RUN-PLANE.md measures 2 at 10 runs/hour."
  type        = number
  default     = 0
}

variable "runner_max_size" {
  type    = number
  default = 4
}
