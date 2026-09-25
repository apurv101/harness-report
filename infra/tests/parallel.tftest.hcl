mock_provider "aws" {
  override_during = plan
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/test" }
  }
  mock_resource "aws_iam_instance_profile" {
    defaults = { arn = "arn:aws:iam::123456789012:instance-profile/test" }
  }
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
  mock_data "aws_route53_zone" {
    defaults = { zone_id = "Z0123456789" }
  }
  mock_data "aws_subnets" {
    defaults = { ids = ["subnet-12345678"] }
  }
}
mock_provider "aws" { alias = "acm" }
mock_provider "archive" {
  override_during = plan
  mock_data "archive_file" {
    defaults = {
      output_sha256       = "test-release"
      output_base64sha256 = "dGVzdA=="
    }
  }
}


override_resource {
  target          = aws_acm_certificate.site
  override_during = plan
  values = {
    arn = "arn:aws:acm:us-east-1:123456789012:certificate/12345678-1234-1234-1234-123456789012"
    domain_validation_options = [{
      domain_name           = "harnessreport.com"
      resource_record_name  = "_test.harnessreport.com"
      resource_record_type  = "CNAME"
      resource_record_value = "_test.acm-validations.aws"
    }]
  }
}


run "parallel_workers" {
  command = plan
  variables {
    enable_run_plane        = true
    runner_warm_pool        = 2
    runner_dispatch_enabled = true
  }
  assert {
    condition     = aws_sqs_queue.evaluations.fifo_queue && !coalesce(aws_sqs_queue.leases.fifo_queue, false)
    error_message = "The FIFO queue must be new; the standard queue must remain available for migration."
  }
  assert {
    condition     = aws_autoscaling_group.runner[0].desired_capacity == 0 && aws_autoscaling_group.runner[0].min_size == 0
    error_message = "Idle fleets must have zero running workers."
  }
  assert {
    condition     = one(aws_autoscaling_group.runner[0].warm_pool).pool_state == "Stopped" && one(aws_autoscaling_group.runner[0].warm_pool).max_group_prepared_capacity == 2 && !one(one(aws_autoscaling_group.runner[0].warm_pool).instance_reuse_policy).reuse_on_scale_in
    error_message = "Standby must contain stopped, unused VMs; used workers cannot return to the pool."
  }
  assert {
    condition     = aws_lambda_function.scaler[0].reserved_concurrent_executions == 1 && aws_lambda_function.api.environment[0].variables.HR_SCALER_FUNCTION == "harness-report-worker-capacity"
    error_message = "Submission must wake a serialized demand controller."
  }
  assert {
    condition     = aws_lambda_function.api.environment[0].variables.HR_EVALS == "queue" && lookup(aws_lambda_function.api.environment[0].variables, "HR_LOCAL_USERS", "0") == "0"
    error_message = "AWS must use the cloud queue and original GitHub flow."
  }
  assert {
    condition     = strcontains(file("${path.module}/runner-init.sh"), "hr-agentd --retire-after-job") && length(aws_launch_template.runner) == 1
    error_message = "Each EC2 instance must actually start the disposable queue worker."
  }
  assert {
    condition     = aws_iam_role.proxy_model[0].name != aws_iam_role.runner[0].name
    error_message = "The proxy must receive a separate model role."
  }
  assert {
    condition     = aws_launch_template.runner[0].metadata_options[0].http_put_response_hop_limit == 1
    error_message = "Harness containers must not gain access to the instance credentials."
  }
}

run "cold_on_demand" {
  command = plan
  variables {
    enable_run_plane        = true
    runner_dispatch_enabled = true
    runner_warm_pool        = 0
  }
  assert {
    condition     = length(aws_autoscaling_group.runner[0].warm_pool) == 0 && aws_lambda_function.scaler[0].environment[0].variables.HR_DISPATCH == "1"
    error_message = "Without standby, demand must still launch fresh workers from zero."
  }
}

run "queue_without_workers" {
  command = plan
  variables {
    enable_run_plane = false
    runner_warm_pool = 0
  }
  assert {
    condition     = length(aws_autoscaling_group.runner) == 0 && aws_sqs_queue.evaluations.fifo_queue
    error_message = "The durable queue must remain available without provisioning compute."
  }
}
