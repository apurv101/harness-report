# ---------------------------------------------------------------- the built frontend

resource "aws_s3_bucket" "site" {
  bucket        = "${local.name}-site-${local.account}"
  force_destroy = true # web/dist is a build artifact; `terraform destroy` should not need a manual empty
}

resource "aws_s3_bucket_public_access_block" "site" {
  bucket                  = aws_s3_bucket.site.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "site" {
  bucket = aws_s3_bucket.site.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

data "aws_iam_policy_document" "site_bucket" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.site.arn}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.site.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "site" {
  bucket = aws_s3_bucket.site.id
  policy = data.aws_iam_policy_document.site_bucket.json
}

# ---------------------------------------------------------------- the distribution

resource "aws_cloudfront_origin_access_control" "site" {
  name                              = "${local.name}-site"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_function" "edge" {
  name    = "${local.name}-edge"
  runtime = "cloudfront-js-2.0"
  publish = true
  code    = file("${path.module}/edge.js")
}

resource "aws_cloudfront_distribution" "site" {
  enabled             = true
  is_ipv6_enabled     = true
  comment             = "${local.name}: web/dist from S3, /api /auth /raw from serve.py on Lambda"
  aliases             = local.aliases
  price_class         = var.price_class
  default_root_object = "index.html"

  origin {
    origin_id                = "site"
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.site.id
  }

  # The function URL is unauthenticated and carries a random 32-char id; the shared secret below is
  # what actually gates it, and handler.py rejects anything without it.  OAC would be the tighter
  # answer, but OAC on a function URL makes the *browser* responsible for sending
  # x-amz-content-sha256 on every POST, which would put CloudFront's signing scheme in the frontend.
  origin {
    origin_id   = "api"
    domain_name = replace(replace(aws_lambda_function_url.api.function_url, "https://", ""), "/", "")

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
      origin_read_timeout    = var.lambda_timeout_s
    }

    custom_header {
      name  = "x-hr-origin"
      value = random_password.origin.result
    }
  }

  default_cache_behavior {
    target_origin_id           = "site"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = data.aws_cloudfront_cache_policy.optimized.id
    response_headers_policy_id = data.aws_cloudfront_response_headers_policy.security.id

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.edge.arn
    }
  }

  # /api, /auth and /raw are serve.py.  Nothing here is cached: the runs list changes while a run is
  # in flight, and /api/me is per-session.
  dynamic "ordered_cache_behavior" {
    for_each = ["/api/*", "/auth/*", "/raw/*"]

    content {
      path_pattern             = ordered_cache_behavior.value
      target_origin_id         = "api"
      viewer_protocol_policy   = "redirect-to-https"
      allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
      cached_methods           = ["GET", "HEAD"]
      compress                 = true
      cache_policy_id          = data.aws_cloudfront_cache_policy.disabled.id
      origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_but_host.id

      function_association {
        event_type   = "viewer-request"
        function_arn = aws_cloudfront_function.edge.arn
      }
    }
  }

  restrictions {
    geo_restriction { restriction_type = "none" }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.site.certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }
}
