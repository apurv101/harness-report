# Terraform ships the worker from this checkout, including uncommitted changes in a local plan.
# Secrets, local users, task data, results and working clones are excluded from the release.
locals {
  runner_files = toset(concat(
    ["run.sh", "hr-agentd", "evals.py", "auth.py", "proxy.py", "policy.py", "infra/runner-lifecycle.py", "requirements-harbor.txt"],
    tolist(fileset("${path.module}/..", "lib/*.py")),
    tolist(fileset("${path.module}/..", "lib/*.sh")),
    tolist(fileset("${path.module}/..", "lib/*.json")),
    tolist(fileset("${path.module}/..", "lib/*.md")),
    tolist(fileset("${path.module}/..", "recipes/*.json")),
  ))
}

data "archive_file" "runner" {
  count       = local.runner
  type        = "zip"
  output_path = "${path.module}/.build/runner.zip"
  dynamic "source" {
    for_each = local.runner_files
    content {
      content  = file("${path.module}/../${source.value}")
      filename = source.value
    }
  }
}

resource "aws_s3_bucket" "runner_assets" {
  count         = local.runner
  bucket        = "${local.name}-runner-assets-${local.account}"
  force_destroy = var.allow_data_destroy
}

resource "aws_s3_bucket_public_access_block" "runner_assets" {
  count                   = local.runner
  bucket                  = aws_s3_bucket.runner_assets[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "runner_assets" {
  count  = local.runner
  bucket = aws_s3_bucket.runner_assets[0].id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_object" "runner_release" {
  count       = local.runner
  bucket      = aws_s3_bucket.runner_assets[0].id
  key         = "releases/${data.archive_file.runner[0].output_sha256}.zip"
  source      = data.archive_file.runner[0].output_path
  source_hash = data.archive_file.runner[0].output_sha256
  lifecycle { create_before_destroy = true }
}
