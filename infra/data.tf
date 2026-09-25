data "aws_caller_identity" "me" {}

data "aws_route53_zone" "site" {
  name         = "${var.domain}."
  private_zone = false
}

# Managed policies, by name rather than by the well-known id.
data "aws_cloudfront_cache_policy" "optimized" { name = "Managed-CachingOptimized" }
data "aws_cloudfront_cache_policy" "disabled" { name = "Managed-CachingDisabled" }
data "aws_cloudfront_origin_request_policy" "all_but_host" { name = "Managed-AllViewerExceptHostHeader" }
data "aws_cloudfront_response_headers_policy" "security" { name = "Managed-SecurityHeadersPolicy" }
