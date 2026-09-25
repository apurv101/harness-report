locals {
  scaler_name = "${local.name}-worker-capacity"
  scaler_arn  = "arn:aws:lambda:${var.region}:${local.account}:function:${local.scaler_name}"
}

data "archive_file" "scaler" {
  count       = local.runner
  type        = "zip"
  output_path = "${path.module}/.build/scaler.zip"
  dynamic "source" {
    for_each = toset(["cloudscale.py", "cloudqueue.py", "ddb.py"])
    content {
      content  = file("${path.module}/../lib/${source.value}")
      filename = source.value
    }
  }
}

resource "aws_iam_role" "scaler" {
  count              = local.runner
  name               = local.scaler_name
  assume_role_policy = data.aws_iam_policy_document.api_assume.json
}

resource "aws_iam_role_policy" "scaler" {
  count = local.runner
  role  = aws_iam_role.scaler[0].id
  name  = "worker-capacity"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow", Action = ["autoscaling:DescribeAutoScalingGroups"], Resource = "*"
      },
      {
        Effect   = "Allow", Action = ["autoscaling:SetDesiredCapacity", "autoscaling:TerminateInstanceInAutoScalingGroup"],
        Resource = "arn:aws:autoscaling:${var.region}:${local.account}:autoScalingGroup:*:autoScalingGroupName/${local.name}-runner"
      },
      {
        Effect   = "Allow", Action = ["dynamodb:Query", "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem", "dynamodb:UpdateItem"],
        Resource = aws_dynamodb_table.store.arn
      },
      {
        Effect   = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"],
        Resource = "${aws_cloudwatch_log_group.scaler[0].arn}:*"
      }
    ]
  })
}

resource "aws_cloudwatch_log_group" "scaler" {
  count             = local.runner
  name              = "/aws/lambda/${local.scaler_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "scaler" {
  count                          = local.runner
  function_name                  = local.scaler_name
  role                           = aws_iam_role.scaler[0].arn
  runtime                        = "python3.13"
  handler                        = "cloudscale.handler"
  filename                       = data.archive_file.scaler[0].output_path
  source_code_hash               = data.archive_file.scaler[0].output_base64sha256
  timeout                        = 30
  memory_size                    = 256
  reserved_concurrent_executions = 1
  environment {
    variables = {
      HR_TABLE    = var.table_name
      HR_ASG_NAME = "${local.name}-runner"
      HR_DISPATCH = var.runner_dispatch_enabled ? "1" : "0"
    }
  }
  depends_on = [aws_iam_role_policy.scaler]
}

# Submission invokes the controller immediately; this repairs missed notifications
# and expired jobs without relying on delayed SQS CloudWatch metrics to wake from zero.
resource "aws_cloudwatch_event_rule" "worker_reconcile" {
  count               = local.runner
  name                = "${local.name}-worker-reconcile"
  schedule_expression = "rate(1 minute)"
}

resource "aws_cloudwatch_event_target" "worker_reconcile" {
  count = local.runner
  rule  = aws_cloudwatch_event_rule.worker_reconcile[0].name
  arn   = aws_lambda_function.scaler[0].arn
}

resource "aws_lambda_permission" "worker_reconcile" {
  count         = local.runner
  statement_id  = "ScheduledWorkerReconcile"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.scaler[0].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.worker_reconcile[0].arn
}
