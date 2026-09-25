# ---------------------------------------------------------------- certificate

resource "aws_acm_certificate" "site" {
  provider                  = aws.acm
  domain_name               = var.domain
  subject_alternative_names = ["www.${var.domain}"]
  validation_method         = "DNS"

  lifecycle { create_before_destroy = true }
}

resource "aws_route53_record" "validation" {
  for_each = {
    for o in aws_acm_certificate.site.domain_validation_options : o.domain_name => {
      name = o.resource_record_name, type = o.resource_record_type, record = o.resource_record_value
    }
  }

  zone_id         = data.aws_route53_zone.site.zone_id
  name            = each.value.name
  type            = each.value.type
  records         = [each.value.record]
  ttl             = 60
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "site" {
  provider                = aws.acm
  certificate_arn         = aws_acm_certificate.site.arn
  validation_record_fqdns = [for r in aws_route53_record.validation : r.fqdn]
}

# ---------------------------------------------------------------- the domain

# Apex and www both point at the distribution; the edge function 301s www to the apex, so the
# second record exists to catch the name, not to serve it.
resource "aws_route53_record" "site" {
  for_each = toset(flatten([for a in local.aliases : ["A:${a}", "AAAA:${a}"]]))

  zone_id = data.aws_route53_zone.site.zone_id
  name    = split(":", each.value)[1]
  type    = split(":", each.value)[0]

  alias {
    name                   = aws_cloudfront_distribution.site.domain_name
    zone_id                = aws_cloudfront_distribution.site.hosted_zone_id
    evaluate_target_health = false
  }
}
