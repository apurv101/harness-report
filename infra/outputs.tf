output "site_url" {
  description = "The site, once the DNS records and the certificate have settled."
  value       = "https://${local.host}"
}

output "cloudfront_domain" {
  description = "The distribution's own name — useful before DNS points at it."
  value       = aws_cloudfront_distribution.site.domain_name
}

output "cloudfront_distribution_id" {
  description = "What the deploy workflow invalidates."
  value       = aws_cloudfront_distribution.site.id
}

output "site_bucket" {
  description = "Where web/dist is synced."
  value       = aws_s3_bucket.site.bucket
}

output "runs_bucket" { value = aws_s3_bucket.runs.bucket }
output "recipes_bucket" { value = aws_s3_bucket.recipes.bucket }
output "table_name" { value = aws_dynamodb_table.store.name }

output "api_function_url" {
  description = "The origin behind /api, /auth and /raw.  Reachable only with the x-hr-origin header."
  value       = aws_lambda_function_url.api.function_url
}

output "deploy_role_arn" {
  description = "Set as AWS_DEPLOY_ROLE in the repository's Actions variables."
  value       = aws_iam_role.deploy.arn
}

output "ecr_overlay" { value = aws_ecr_repository.overlay.repository_url }
output "ecr_proxy" { value = aws_ecr_repository.proxy.repository_url }

output "lease_queue_url" {
  description = "Where the API puts evaluations and hr-agentd takes them.  Export it as HR_QUEUE_URL."
  value       = aws_sqs_queue.evaluations.url
}

output "secrets_to_fill" {
  description = "Not managed here.  `./bootstrap.sh secrets` creates and fills these from ../.env."
  value       = [for s in local.secrets : "/${local.name}/${s}"]
}

output "legacy_lease_queue_url" {
  description = "The old standard queue, retained so existing messages can be drained before retirement."
  value       = aws_sqs_queue.leases.url
}

output "runner_assets_bucket" {
  description = "Upload the Harbor corpus under tasks/<taskset>/<task>/ before starting workers."
  value       = try(aws_s3_bucket.runner_assets[0].bucket, null)
}

output "worker_capacity_function" {
  description = "Demand controller invoked on submissions and periodically for reconciliation."
  value       = try(aws_lambda_function.scaler[0].function_name, null)
}
