# Disposable EC2 workers: one evaluation per VM, separate users run on separate kernels.
# A short-lived controller wakes stopped workers on demand; no running idle minimum.

locals {
  runner = var.enable_run_plane ? 1 : 0
}

# ---------------------------------------------------------------- the runner's identity

data "aws_iam_policy_document" "runner_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "runner" {
  count = local.runner

  statement {
    sid       = "Leases"
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:ChangeMessageVisibility", "sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.evaluations.arn]
  }

  statement {
    sid       = "RunFolders"
    actions   = ["s3:PutObject", "s3:GetObject", "s3:ListBucket", "s3:AbortMultipartUpload"]
    resources = [aws_s3_bucket.runs.arn, "${aws_s3_bucket.runs.arn}/*"]
  }

  statement {
    sid       = "Recipes"
    actions   = ["s3:PutObject", "s3:GetObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.recipes.arn, "${aws_s3_bucket.recipes.arn}/*"]
  }

  statement {
    sid       = "RunStore"
    actions   = ["dynamodb:DescribeTable", "dynamodb:PutItem", "dynamodb:DeleteItem", "dynamodb:BatchWriteItem", "dynamodb:GetItem", "dynamodb:Query", "dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.store.arn, "${aws_dynamodb_table.store.arn}/index/*"]
  }

  statement {
    sid       = "Overlays"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid = "OverlayPush"
    actions = [
      "ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage", "ecr:CompleteLayerUpload",
      "ecr:GetDownloadUrlForLayer", "ecr:InitiateLayerUpload", "ecr:PutImage", "ecr:UploadLayerPart",
    ]
    resources = [aws_ecr_repository.overlay.arn, aws_ecr_repository.proxy.arn]
  }

  # The model route.  proxy.py holds these credentials; the harness container is on an --internal
  # network and never sees them.
  statement {
    sid       = "Model"
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = ["*"]
  }

  statement {
    sid       = "RunnerAssets"
    actions   = ["s3:GetObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.runner_assets[0].arn, "${aws_s3_bucket.runner_assets[0].arn}/*"]
  }

  statement {
    sid       = "PrivateCloneKey"
    actions   = ["ssm:GetParameter"]
    resources = ["arn:aws:ssm:${var.region}:${local.account}:parameter/${local.name}/GITHUB_APP_KEY"]
  }

  statement {
    sid       = "ProxyModelSession"
    actions   = ["sts:AssumeRole"]
    resources = [aws_iam_role.proxy_model[0].arn]
  }

  statement {
    sid       = "JobProtection"
    actions   = ["autoscaling:SetInstanceProtection", "autoscaling:CompleteLifecycleAction"]
    resources = ["arn:aws:autoscaling:${var.region}:${local.account}:autoScalingGroup:*:autoScalingGroupName/${local.name}-runner"]
  }

  statement {
    actions   = ["autoscaling:DescribeAutoScalingInstances"]
    resources = ["*"]
  }

  statement {
    sid       = "RetireWorker"
    actions   = ["lambda:InvokeFunction"]
    resources = [local.scaler_arn]
  }

}

resource "aws_iam_role" "runner" {
  count              = local.runner
  name               = "${local.name}-runner"
  assume_role_policy = data.aws_iam_policy_document.runner_assume.json
}

resource "aws_iam_role_policy" "runner" {
  count  = local.runner
  name   = "runner"
  role   = aws_iam_role.runner[0].id
  policy = data.aws_iam_policy_document.runner[0].json
}

# SSM Session Manager is the only way in — no SSH, no keys, no port 22.
resource "aws_iam_role_policy_attachment" "runner_ssm" {
  count      = local.runner
  role       = aws_iam_role.runner[0].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "runner" {
  count = local.runner
  name  = "${local.name}-runner"
  role  = aws_iam_role.runner[0].name
}

# ---------------------------------------------------------------- the machine

data "aws_ami" "ubuntu" {
  count       = local.runner
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }
}

resource "aws_security_group" "runner" {
  count       = local.runner
  name        = "${local.name}-runner"
  description = "Runners reach out; nothing reaches in (SSM only)."
  vpc_id      = data.aws_vpc.default[0].id

  egress {
    description = "the model, the registries, and whatever a build pulls"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

data "aws_vpc" "default" {
  count   = local.runner
  default = true
}

data "aws_subnets" "default" {
  count = local.runner
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default[0].id]
  }
}

resource "aws_launch_template" "runner" {
  count         = local.runner
  name          = "${local.name}-runner"
  image_id      = var.runner_ami_id != "" ? var.runner_ami_id : data.aws_ami.ubuntu[0].id
  instance_type = var.runner_instance_type

  iam_instance_profile { arn = aws_iam_instance_profile.runner[0].arn }
  vpc_security_group_ids = [aws_security_group.runner[0].id]

  # Only never-used instances are stopped in the warm pool. Used workers terminate.
  instance_initiated_shutdown_behavior = "terminate"

  block_device_mappings {
    device_name = "/dev/sda1"
    ebs {
      volume_size           = var.runner_disk_gb
      volume_type           = "gp3"
      throughput            = 250
      delete_on_termination = true
      encrypted             = true
    }
  }

  # No container may read the instance role: the internal network already has no route to the
  # metadata endpoint, and a hop limit of 1 is the belt to that braces.
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  monitoring { enabled = true }

  user_data = base64encode(templatefile("${path.module}/runner-init.sh", {
    region          = var.region
    queue_url       = aws_sqs_queue.evaluations.url
    runs_bucket     = aws_s3_bucket.runs.bucket
    recipes_bucket  = aws_s3_bucket.recipes.bucket
    table           = var.table_name
    assets_bucket   = aws_s3_bucket.runner_assets[0].bucket
    release_key     = aws_s3_object.runner_release[0].key
    model           = var.runner_model
    analyzer_model  = var.runner_analyzer_model
    model_role      = aws_iam_role.proxy_model[0].arn
    github_app_id   = var.github_app_id
    secret_prefix   = "/${local.name}/"
    asg_name        = "${local.name}-runner"
    max_seconds     = var.runner_max_job_seconds
    scaler_function = local.scaler_name
    install_script  = file("${path.module}/runner-install.sh")
    service_seconds = var.runner_max_job_seconds + 600
  }))

  tag_specifications {
    resource_type = "instance"
    tags          = merge(local.tags, { Name = "${local.name}-runner" })
  }
}

resource "aws_autoscaling_group" "runner" {
  count                 = local.runner
  name                  = "${local.name}-runner"
  vpc_zone_identifier   = data.aws_subnets.default[0].ids
  min_size              = 0
  max_size              = var.runner_max_size
  desired_capacity      = 0
  protect_from_scale_in = true

  initial_lifecycle_hook {
    name                 = "worker-ready"
    lifecycle_transition = "autoscaling:EC2_INSTANCE_LAUNCHING"
    heartbeat_timeout    = 1800
    default_result       = "ABANDON"
  }

  dynamic "warm_pool" {
    for_each = var.runner_dispatch_enabled && var.runner_warm_pool > 0 ? [1] : []
    content {
      pool_state                  = "Stopped"
      min_size                    = var.runner_warm_pool
      max_group_prepared_capacity = var.runner_warm_pool
      instance_reuse_policy { reuse_on_scale_in = false }
    }
  }

  launch_template {
    id      = aws_launch_template.runner[0].id
    version = "$Latest"
  }

  # Boot installs the release, then systemd starts the queue consumer.
  health_check_type         = "EC2"
  health_check_grace_period = 900
  capacity_rebalance        = false

  instance_refresh {
    strategy = "Rolling"
    preferences {
      min_healthy_percentage       = 100
      max_healthy_percentage       = 150
      scale_in_protected_instances = "Wait"
      skip_matching                = true
    }
  }

  lifecycle {
    ignore_changes = [desired_capacity]
    precondition {
      condition     = var.runner_warm_pool >= 0 && var.runner_warm_pool <= var.runner_max_size && var.runner_warm_pool == floor(var.runner_warm_pool)
      error_message = "runner_warm_pool must be a whole number between 0 and runner_max_size."
    }
  }

  depends_on = [aws_iam_role_policy.runner, aws_iam_role_policy.proxy_model, aws_lambda_function.scaler]

  dynamic "tag" {
    for_each = local.tags
    content {
      key                 = tag.key
      value               = tag.value
      propagate_at_launch = true
    }
  }
}

# The proxy can call models, but cannot read the queue, table, source bundle or app key.
resource "aws_iam_role" "proxy_model" {
  count = local.runner
  name  = "${local.name}-proxy-model"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { AWS = aws_iam_role.runner[0].arn }
    }]
  })
}

resource "aws_iam_role_policy" "proxy_model" {
  count = local.runner
  role  = aws_iam_role.proxy_model[0].id
  name  = "model-only"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
      Resource = "*"
    }]
  })
}
