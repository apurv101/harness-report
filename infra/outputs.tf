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
  description = "Empty until enable_run_plane is true."
  value       = try(aws_sqs_queue.leases[0].url, "")
}

output "secrets_to_fill" {
  description = "SecureStrings created empty.  ./bootstrap.sh secrets pushes them out of .env."
  value       = [for s in local.secrets : "/${local.name}/${s}"]
}
