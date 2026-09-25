# ---------------------------------------------------------------- GitHub Actions
#
# OIDC, so CI holds no keys.  GitHub mints a token for the workflow, AWS trades it for this role, and
# the role expires with the job.  The trust is scoped to one repository; the branch condition below
# is what keeps a fork's pull request from assuming it.

data "aws_iam_openid_connect_provider" "github" {
  count = var.create_oidc_provider ? 0 : 1
  url   = "https://token.actions.githubusercontent.com"
}

resource "aws_iam_openid_connect_provider" "github" {
  count           = var.create_oidc_provider ? 1 : 0
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

locals {
  oidc_arn = var.create_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : data.aws_iam_openid_connect_provider.github[0].arn
}

data "aws_iam_policy_document" "deploy_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.oidc_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # main, and pull requests (plan only — the workflow, not the role, is what withholds apply).
    #
    # Each subject is listed once per naming form.  Never widen these to `repo:apurv101*/...`:
    # the wildcard would also match `apurv10100`, which is a different account.
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values = flatten([
        for repo in compact([var.github_repo, var.github_repo_ids]) : [
          "repo:${repo}:ref:refs/heads/main",
          "repo:${repo}:pull_request",
          "repo:${repo}:environment:production",
        ]
      ])
    }
  }
}

resource "aws_iam_role" "deploy" {
  name                 = "${local.name}-deploy"
  description          = "GitHub Actions: terraform apply, the web build to S3, and the invalidation"
  assume_role_policy   = data.aws_iam_policy_document.deploy_assume.json
  max_session_duration = 3600
}

# Deliberately broad on the services this stack uses and silent on everything else: a deploy role
# that cannot create the next resource is a deploy role someone edits by hand at 2am.  It is bounded
# by service, not by resource, and the account holds nothing else.
resource "aws_iam_role_policy" "deploy" {
  name = "deploy"
  role = aws_iam_role.deploy.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "Stack"
        Effect = "Allow"
        Action = [
          "s3:*", "cloudfront:*", "lambda:*", "dynamodb:*", "ecr:*", "sqs:*",
          "acm:*", "route53:*", "logs:*", "ssm:*", "autoscaling:*", "ec2:*", "events:*",
          "iam:GetRole", "iam:PassRole", "iam:CreateRole", "iam:DeleteRole", "iam:TagRole",
          "iam:GetRolePolicy", "iam:PutRolePolicy", "iam:DeleteRolePolicy",
          "iam:ListRolePolicies", "iam:ListAttachedRolePolicies", "iam:ListInstanceProfilesForRole",
          "iam:AttachRolePolicy", "iam:DetachRolePolicy", "iam:UpdateAssumeRolePolicy",
          "iam:CreateInstanceProfile", "iam:DeleteInstanceProfile",
          "iam:AddRoleToInstanceProfile", "iam:RemoveRoleFromInstanceProfile", "iam:GetInstanceProfile",
          "iam:GetOpenIDConnectProvider", "iam:CreateServiceLinkedRole",
          "sts:GetCallerIdentity",
        ]
        Resource = "*"
      },
      {
        # Reading a SecureString is how the *Lambda* works, not how a deploy works.  CI may write a
        # placeholder and never read a value back.
        Sid      = "NoSecretReads"
        Effect   = "Deny"
        Action   = ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"]
        Resource = "arn:aws:ssm:${var.region}:${local.account}:parameter/${local.name}/*"
      },
    ]
  })
}
