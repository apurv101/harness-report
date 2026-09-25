# ---------------------------------------------------------------- the package
#
# serve.py, its two siblings at the repo root and all of lib/, zipped by Terraform itself.  There is
# no build step for the API: the files are already dependency-free python3, and the runtime supplies
# boto3 for the one thing handler.py needs it for (reading the secrets at cold start).

data "archive_file" "api" {
  type        = "zip"
  output_path = "${path.module}/.build/api.zip"

  source {
    content  = file("${path.module}/../lambda/handler.py")
    filename = "handler.py"
  }

  dynamic "source" {
    for_each = local.lambda_files
    content {
      content  = file("${path.module}/../${source.value}")
      filename = source.value
    }
  }
}

# ---------------------------------------------------------------- secrets
#
# Deliberately NOT Terraform resources.  `./bootstrap.sh secrets` creates the three SecureStrings and
# writes their values; the Lambda reads them by path at cold start; Terraform only ever names the
# path in an IAM policy.
#
# The first attempt did manage them, holding "unset" with `ignore_changes = [value]`, and it was
# wrong in a way that only CI could show: Terraform *refreshes* every resource it manages, so every
# plan called ssm:GetParameter — which the deploy role explicitly denies (cicd.tf).  `ignore_changes`
# governs what Terraform does with a diff, not whether it reads.  Managing them and forbidding CI to
# read them cannot both be true, and of the two, not reading them is the one worth keeping.
#
# The cost is that `terraform destroy` leaves the three parameters behind.  That is the right
# default for something a person put there by hand.

resource "random_password" "origin" {
  length  = 48
  special = false
}

# ---------------------------------------------------------------- the function

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/${local.name}-api"
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "api_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "api" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.api.arn}:*"]
  }

  # Reads against the run store, plus the rows the site itself writes: sessions, and the card for an evaluation
  # it has queued.  No UpdateItem — that is the store's own rule (lib/store.py), not an accident of this policy.
  # BatchWriteItem is not optional despite the small writes: store.publish_card batches its two rows, and
  # auth._drop deletes a session partition the same way, so without it signing out fails quietly.
  statement {
    sid = "RunStore"
    actions = [
      # DescribeTable is not bookkeeping: store.available() is how serve.py decides whether to answer from the
      # table or from run folders, and it asks by describing the table.  Denied, it throws, the throw is caught,
      # and the API quietly serves the empty list of folders a Lambda does not have — a permissions gap that
      # looks exactly like an empty table.
      "dynamodb:DescribeTable",
      "dynamodb:GetItem", "dynamodb:Query",
      "dynamodb:PutItem", "dynamodb:DeleteItem", "dynamodb:BatchWriteItem",
    ]
    resources = [aws_dynamodb_table.store.arn, "${aws_dynamodb_table.store.arn}/index/*"]
  }

  statement {
    sid       = "Secrets"
    actions   = ["ssm:GetParametersByPath", "ssm:GetParameter", "ssm:GetParameters"]
    resources = ["arn:aws:ssm:${var.region}:${local.account}:parameter/${local.name}/*"]
  }

  # Enqueue only.  The API puts work on the queue and never takes any off: consuming a lease is the runner's
  # business, and a control plane able to drain its own queue can quietly lose a run.
  statement {
    sid       = "Enqueue"
    actions   = ["sqs:SendMessage", "sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.leases.arn]
  }

  statement {
    sid       = "RunFiles"
    actions   = ["s3:GetObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.runs.arn, "${aws_s3_bucket.runs.arn}/*"]
  }
}

resource "aws_iam_role" "api" {
  name               = "${local.name}-api"
  assume_role_policy = data.aws_iam_policy_document.api_assume.json
}

resource "aws_iam_role_policy" "api" {
  name   = "api"
  role   = aws_iam_role.api.id
  policy = data.aws_iam_policy_document.api.json
}

resource "aws_lambda_function" "api" {
  function_name    = "${local.name}-api"
  role             = aws_iam_role.api.arn
  runtime          = "python3.13"
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.api.output_path
  source_code_hash = data.archive_file.api.output_base64sha256
  memory_size      = var.lambda_memory_mb
  timeout          = var.lambda_timeout_s

  environment {
    variables = {
      HR_PUBLIC_HOST   = local.host
      HR_ORIGIN_SECRET = random_password.origin.result
      HR_SECRET_PREFIX = "/${local.name}/"
      HR_TABLE         = var.table_name
      HR_SESSIONS      = "ddb"   # sessions are rows, not .auth/sessions.json — Lambda has no disk to share
      HR_EVALS         = "queue" # record it and enqueue it; a runner with a Docker daemon does the work
      HR_QUEUE_URL     = aws_sqs_queue.leases.url
      HR_RUNS_BUCKET   = aws_s3_bucket.runs.bucket
      BASE_URL         = "https://${local.host}"
      GITHUB_CLIENT_ID = var.github_client_id
      GITHUB_APP_ID    = var.github_app_id
      GITHUB_APP_SLUG  = var.github_app_slug
    }
  }

  depends_on = [aws_cloudwatch_log_group.api]
}

resource "aws_lambda_function_url" "api" {
  function_name      = aws_lambda_function.api.function_name
  authorization_type = "NONE"
}

# AuthType NONE does not grant itself: without this the url answers 403 to everyone, CloudFront
# included.  What actually gates the origin is the x-hr-origin header handler.py checks (site.tf).
resource "aws_lambda_permission" "url" {
  statement_id           = "AllowFunctionUrl"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.api.function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}
