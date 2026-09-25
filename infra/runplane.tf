# ---------------------------------------------------------------- the run plane
#
# RUN-PLANE.md, as infrastructure.  Everything here is behind `enable_run_plane`, and it is false by
# default for one honest reason: hr-agentd — the poller that leases from the queue, runs run.sh's
# stages and syncs the folder to S3 — is not written yet.  The queue, the role and the launch
# template are correct and cost nothing at zero desired capacity; the fleet is what waits.
#
# The shape, from the measurements in that document: one VM per evaluation session (user x harness),
# many task containers on it, because image locality is worth 30-60 s on a 53 s job.

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
    resources = [aws_sqs_queue.leases.arn]
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
    actions   = ["dynamodb:PutItem", "dynamodb:BatchWriteItem", "dynamodb:GetItem", "dynamodb:Query"]
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

  # An instance tags itself hr:state=free when its images are pulled, and the allocator flips it to
  # leased.  Scoped by the tag it is allowed to write, not by instance.
  statement {
    sid       = "SelfTag"
    actions   = ["ec2:CreateTags", "ec2:DescribeTags", "ec2:DescribeInstances"]
    resources = ["*"]
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
  image_id      = data.aws_ami.ubuntu[0].id
  instance_type = var.runner_instance_type

  iam_instance_profile { arn = aws_iam_instance_profile.runner[0].arn }
  vpc_security_group_ids = [aws_security_group.runner[0].id]

  # The disk is a cache, never state, so the instance terminates rather than stops: instance store
  # is wiped on stop and there is nothing worth keeping on the root volume either.
  instance_initiated_shutdown_behavior = "terminate"

  block_device_mappings {
    device_name = "/dev/sda1"
    ebs {
      volume_size           = 30
      volume_type           = "gp3"
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
    region         = var.region
    queue_url      = aws_sqs_queue.leases.url
    runs_bucket    = aws_s3_bucket.runs.bucket
    recipes_bucket = aws_s3_bucket.recipes.bucket
    table          = var.table_name
    registry       = "${local.account}.dkr.ecr.${var.region}.amazonaws.com"
  }))

  tag_specifications {
    resource_type = "instance"
    tags          = merge(local.tags, { Name = "${local.name}-runner" })
  }
}

resource "aws_autoscaling_group" "runner" {
  count               = local.runner
  name                = "${local.name}-runner"
  vpc_zone_identifier = data.aws_subnets.default[0].ids
  min_size            = 0
  max_size            = var.runner_max_size
  desired_capacity    = var.runner_warm_pool

  launch_template {
    id      = aws_launch_template.runner[0].id
    version = "$Latest"
  }

  # An instance only counts as ready once runner-init.sh has pulled the bake list and tagged itself
  # free; until then the pool is deeper than it looks.
  health_check_type         = "EC2"
  health_check_grace_period = 300
  capacity_rebalance        = false

  instance_refresh {
    strategy = "Rolling"
    preferences { min_healthy_percentage = 0 }
  }

  tag {
    key                 = "hr:state"
    value               = "booting"
    propagate_at_launch = true
  }

  dynamic "tag" {
    for_each = local.tags
    content {
      key                 = tag.key
      value               = tag.value
      propagate_at_launch = true
    }
  }
}
