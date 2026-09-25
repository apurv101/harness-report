# ---------------------------------------------------------------- the lease queue
#
# One evaluation started on the site is one message here.  This is deliberately NOT behind
# `enable_run_plane`: the queue is the whole coupling between the API and whatever runs the work, and the first
# thing running the work is hr-agentd on a laptop.  The EC2 fleet is one more consumer of the same queue, later.
#
# The API never learns where a run happens and the runner never learns who asked, which is what lets the runner
# move from a laptop to an instance without either side changing.

resource "aws_sqs_queue" "leases_dlq" {
  name                      = "${local.name}-leases-dlq"
  message_retention_seconds = 1209600
}

resource "aws_sqs_queue" "leases" {
  name = "${local.name}-leases"

  # A lease is (user, repo@commit, taskset, tasks, k).  The longest measured agent run is 1192 s and a cold
  # harness adds four minutes of analyzer and build before that, so the window has to outlast the whole
  # evaluation — hr-agentd also pushes it out while it works.  A window that expires under a running job hands
  # the same task to a second runner while the first is still on it.
  visibility_timeout_seconds = 3600
  message_retention_seconds  = 86400

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.leases_dlq.arn
    maxReceiveCount     = 3
  })
}

# New queue rather than replacing the existing standard queue: old messages can be drained safely.
resource "aws_sqs_queue" "evaluations_dlq" {
  name                      = "${local.name}-evaluations-dlq.fifo"
  fifo_queue                = true
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "evaluations" {
  name                        = "${local.name}-evaluations.fifo"
  fifo_queue                  = true
  content_based_deduplication = false
  visibility_timeout_seconds  = 900
  receive_wait_time_seconds   = 20
  message_retention_seconds   = 1209600
  sqs_managed_sse_enabled     = true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.evaluations_dlq.arn
    maxReceiveCount     = 5
  })
}
