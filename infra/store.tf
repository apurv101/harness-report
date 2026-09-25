# ---------------------------------------------------------------- the run store
#
# The schema is lib/store.py's docstring: one table, generic pk/sk, two indexes.  Mirrored here rather
# than created by `./run.sh ddb start`, which is the laptop's path.  Everything is on-demand: the
# traffic is a person opening a run, not a steady rate anyone can provision for.

resource "aws_dynamodb_table" "store" {
  name         = var.table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }
  attribute {
    name = "sk"
    type = "S"
  }
  attribute {
    name = "gsi1pk"
    type = "S"
  }
  attribute {
    name = "gsi1sk"
    type = "S"
  }
  attribute {
    name = "gsi2pk"
    type = "S"
  }
  attribute {
    name = "gsi2sk"
    type = "S"
  }

  # "every run and every recipe of one harness" in one query.
  #
  # The index says its keys as `key_schema` and the table says them as hash_key/range_key, which
  # reads like an inconsistency and is not: aws 6.66 deprecates hash_key in favour of key_schema but
  # only ships the block on the index, so the table has no other way to say it yet.
  global_secondary_index {
    name            = "harness"
    projection_type = "ALL"

    key_schema {
      attribute_name = "gsi1pk"
      key_type       = "HASH"
    }
    key_schema {
      attribute_name = "gsi1sk"
      key_type       = "RANGE"
    }
  }

  # "every harness's runs on one task" in one query — what a task page lists.  Only Harbor run cards carry
  # gsi2pk, so the index holds runs and nothing else.
  global_secondary_index {
    name            = "task"
    projection_type = "ALL"

    key_schema {
      attribute_name = "gsi2pk"
      key_type       = "HASH"
    }
    key_schema {
      attribute_name = "gsi2sk"
      key_type       = "RANGE"
    }
  }

  # Sessions expire themselves.  No run, recipe or eval row carries `ttl`, so nothing else is touched.
  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  point_in_time_recovery { enabled = true }

  # The table is a derived index — `./run.sh ddb sync` rebuilds every row from the run folders — so
  # losing it costs one command, not data.  Still cheap to keep, so it is kept.
  lifecycle { prevent_destroy = false }
}

# ---------------------------------------------------------------- run folders
#
# Where hr-agentd syncs runs/<run-id>/ when the run plane lands, and where /raw/<run-id>/<file> will
# be served from once it holds anything.  Until then the Lambda answers /raw out of the table's
# inlined file text, which is why this bucket can be empty and the site still works.

resource "aws_s3_bucket" "runs" {
  bucket = "${local.name}-runs-${local.account}"

  # False everywhere except the destroy workflow, which passes it explicitly.  A bucket of run
  # folders is the one thing in this stack that is not reproducible from the repo.
  force_destroy = var.allow_data_destroy
}

resource "aws_s3_bucket_public_access_block" "runs" {
  bucket                  = aws_s3_bucket.runs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "runs" {
  bucket = aws_s3_bucket.runs.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

# A run folder measures 13.4 MB and one shipped a whole Node install at 150 MB.  Cold storage after a
# quarter keeps the archive honest without anyone deciding what to delete.
resource "aws_s3_bucket_lifecycle_configuration" "runs" {
  bucket = aws_s3_bucket.runs.id

  rule {
    id     = "age-out"
    status = "Enabled"
    filter {}

    transition {
      days          = 90
      storage_class = "STANDARD_IA"
    }
    abort_incomplete_multipart_upload { days_after_initiation = 7 }
  }
}

# ---------------------------------------------------------------- images
#
# The recipe cache's other half: overlays keyed <harness>@<commit>/<taskset>:<task>, and the proxy.
# Both are pushed by a runner, so they exist before the fleet does.

resource "aws_ecr_repository" "overlay" {
  name                 = "${local.name}/overlay"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration { scan_on_push = false }
}

resource "aws_ecr_repository" "proxy" {
  name                 = "${local.name}/proxy"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration { scan_on_push = false }
}

# 474 GB of instance store holds 100-200 overlays; the registry should not hold every one forever.
resource "aws_ecr_lifecycle_policy" "overlay" {
  repository = aws_ecr_repository.overlay.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "keep the 200 most recent overlays"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 200 }
      action       = { type = "expire" }
    }]
  })
}

# ---------------------------------------------------------------- recipes
#
# recipes/<name>@<sha>.json, the cache that keeps the $0.6-$11 analyzer from running twice on one
# commit.  RUN-PLANE.md calls this the highest-leverage line item in the whole design.

resource "aws_s3_bucket" "recipes" {
  bucket        = "${local.name}-recipes-${local.account}"
  force_destroy = var.allow_data_destroy
}

resource "aws_s3_bucket_public_access_block" "recipes" {
  bucket                  = aws_s3_bucket.recipes.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "recipes" {
  bucket = aws_s3_bucket.recipes.id
  versioning_configuration { status = "Enabled" }
}
