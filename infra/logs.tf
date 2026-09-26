# ---------------------------------------------------------------- Visitor logs
# Every request CloudFront answers, page or API, as one JSON line in CloudWatch Logs.  This is the only place a
# visitor's real address exists: the Lambda sees CloudFront's edge IPs, and S3 hits never reach our code at all.
# admin/ reads it with Logs Insights.
#
# CloudFront's vended logs (standard logging v2) are delivered from us-east-1 whatever region the stack is in, so
# the source, the destination and the log group all live there.

resource "aws_cloudwatch_log_group" "visits" {
  provider          = aws.acm
  name              = "/${local.name}/cloudfront"
  retention_in_days = var.visit_log_retention_days
}

resource "aws_cloudwatch_log_delivery_source" "visits" {
  provider     = aws.acm
  name         = "${local.name}-cloudfront"
  log_type     = "ACCESS_LOGS"
  resource_arn = aws_cloudfront_distribution.site.arn
}

resource "aws_cloudwatch_log_delivery_destination" "visits" {
  provider      = aws.acm
  name          = "${local.name}-cloudfront"
  output_format = "json"

  delivery_destination_configuration {
    destination_resource_arn = aws_cloudwatch_log_group.visits.arn
  }
}

resource "aws_cloudwatch_log_delivery" "visits" {
  provider                 = aws.acm
  delivery_source_name     = aws_cloudwatch_log_delivery_source.visits.name
  delivery_destination_arn = aws_cloudwatch_log_delivery_destination.visits.arn

  # Named rather than defaulted: the default set has no country or ASN, and does have cs(Cookie), which would put
  # session ids in a log.
  record_fields = [
    "timestamp", "c-ip", "c-country", "asn", "cs-method", "x-host-header", "cs-uri-stem", "cs-uri-query",
    "sc-status", "cs(Referer)", "cs(User-Agent)", "x-edge-location", "x-edge-result-type", "x-edge-request-id",
    "sc-bytes", "time-taken", "cs-protocol-version", "sc-content-type",
  ]
}
