# Parallel evaluations on AWS

The hosted browser keeps the original GitHub sign-in → import repository → evaluate
flow. Local test accounts are never enabled by the AWS configuration.

```text
Browser → CloudFront → Lambda API → SQS FIFO → EC2 workers → Docker sandbox + proxy
                           ↕                       ↓
                       DynamoDB              DynamoDB + S3 results
```

Each GitHub login has a separate FIFO message group. Different users run in
parallel, while each user has one active evaluation at a time. The API returns a
job ID immediately; the browser follows that ID and lists the signed-in user's
jobs. Owner checks cover progress, console and cancellation. Completed run reports
remain public, as in the existing application.

## Workers start on demand

The running fleet has a minimum of **zero**. After SQS accepts a job, the API
asynchronously invokes a small capacity-controller Lambda. The controller reads
an atomic, strongly consistent `JOBS#ACTIVE` index in DynamoDB, counts distinct
owners with queued/running work, and sets the fleet's desired capacity up to
`runner_max_size` (default 4). Ten jobs from one user request one worker, not ten.
Only one controller invocation runs at a time. A once-per-minute EventBridge
invocation repairs missed wakeups and expires lost attempts; normal submissions
do not wait for CloudWatch queue metrics or the next scheduled tick.

`runner_warm_pool` now means **unused, stopped standby workers**, default 2. This
replaces its previous meaning of always-running capacity. ASG restores a prepared
worker when demand arrives and replenishes standby in the background. Set it to 0
for fresh launches only. While stopped, the workers incur EBS storage charges;
initial preparation and standby replenishment incur temporary EC2 compute charges.
There is no permanently running idle worker. A burst can exhaust standby and then
incur cold starts. A single evaluation runs on each VM; used VMs are terminated,
never returned to standby or handed to another user.

Lifecycle hooks keep preparation behind a gate: install tools, populate common
Docker layers, then let AWS stop the unused instance. On resume, systemd waits
until the VM is `InService` before reading SQS. Docker caches use encrypted EBS,
not instance-store storage that disappears on stop. A prepared AMI moves tool
installation and common image downloads off the launch path entirely.

On completion, the worker uploads results and finishes recommendation publication,
then asks the same controller to terminate its instance **and decrement desired
capacity**. The controller immediately recalculates remaining demand. The last
job therefore returns running capacity to zero instead of causing an unconditional
replacement. Busy/booting workers are protected from scale-in. Empty workers exit
after 60 seconds, and systemd bounds service runtime if the pipeline hangs.

## Why this execution platform

The priority is time from submission to actual test execution, not just the time
an API takes to accept a launch. The complete path includes dispatch, machine
readiness, task download, missing image builds, harness analysis/build, and tests.

| Option | Fit for this pipeline | Startup tradeoff |
|---|---|---|
| Prepared EC2 + stopped warm pool | Full Docker daemon, isolated VM per evaluation, persistent prepared layers | Chosen: resume prepared machines; replenish fresh standby separately |
| Fresh EC2 from a prepared AMI | Same compatibility and isolation | No standby disks, but a cold launch and snapshot reads on every job |
| CodeBuild on-demand EC2 | Supports Docker builds/runs and destroys machines after builds | Viable managed alternative; custom-image provisioning and cache availability need workload benchmarks |
| AWS Batch on EC2 | Managed batch scheduling and EC2 capacity | Useful for throughput; would add a scheduling layer and needs equivalent isolation/caching work |
| Fargate / Lambda compute | Cannot run this existing privileged Docker workflow unchanged | Requires redesigning image builds and execution; faster container startup alone does not solve that |

AWS documents [stopped warm pools and lifecycle gates](https://docs.aws.amazon.com/autoscaling/ec2/userguide/ec2-auto-scaling-warm-pools.html),
[CodeBuild on-demand versus reserved capacity](https://docs.aws.amazon.com/codebuild/latest/userguide/create-project.html),
[Docker in CodeBuild](https://docs.aws.amazon.com/codebuild/latest/userguide/sample-docker-custom-image.html),
and [Fargate's privileged-container limitation](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-security-considerations.html).
This is a compatibility/latency design choice, **not a measured claim that EC2 is
universally fastest**. Hibernation is another candidate to benchmark against stopped
resume; it needs a supported instance/AMI and adds RAM-restoration behavior.

Measure submit-to-claim, claim-to-first-agent-container, and total evaluation time,
including p50/p95 and bursts exceeding standby. A cache miss or new harness still
needs analysis/build work. The initial AWS measurements are recorded in
[`infra/benchmarks/startup-2026-09-25.json`](infra/benchmarks/startup-2026-09-25.json):

| Probe, 8 vCPU / 16 GiB in us-west-2 | Request to small Docker test completed |
|---|---|
| Prepared EC2, stopped resume (2 samples) | 13.7–14.3 seconds |
| Prepared EC2, fresh launch (1 sample) | 68.0 seconds |
| CodeBuild managed image, Docker only (2 samples) | 14.6–15.2 seconds |
| CodeBuild managed image + install worker tools (2 samples) | 54.5–59.8 seconds |

The EC2 image already includes the analyzer, Python dependencies and common Docker
layers. CodeBuild's underlying compute starts quickly; installing the analyzer on
every job adds most of the measured delay. A custom CodeBuild image or a prebuilt
tool bundle could narrow that difference and has not been measured. These samples
support prepared/stopped EC2 for the current runner; they do not establish a
universal fastest platform or a latency SLA. The probe bypasses the application
queue and ASG, and does not run repository-specific analysis or model calls.

The benchmark creates isolated resources, runs no models, and removes probe VMs,
CodeBuild projects, their roles/logs and probe security groups. The prepared AMI is
retained for the actual worker configuration.

```sh
AWS_PROFILE=operator python3 tests/aws_startup_benchmark.py --codebuild \
  --output infra/.build/codebuild-startup.json
AWS_PROFILE=operator python3 tests/aws_startup_benchmark.py --codebuild --tools \
  --output infra/.build/codebuild-tools-startup.json
AWS_PROFILE=operator python3 tests/aws_startup_benchmark.py --ami ami-07b3adfc7d225a1ea \
  --output infra/.build/ec2-startup.json
```

## State and recovery

- SQS is the delivery queue. A DynamoDB transaction claims a job exactly once.
  Authoritative `JOB#…` rows are separate from the derived report rows, so a log
  publication cannot erase cancellation. Owner lists and the active scheduling
  index update in the same transaction; terminal jobs leave that index.
- Daily submission limits are atomic across Lambda requests. Cancelled jobs return
  their daily slot. Queued cancellation prevents execution; running cancellation
  terminates the process group and removes only that evaluation's Docker resources.
- Workers extend SQS visibility and their DynamoDB lease. Loss of contact stops the
  attempt. On redelivery, expired attempts become failed; paid model calls are not
  automatically repeated. Submit a new evaluation to retry.
- The worker protects its instance from scale-in while running. Shutdown sends a
  termination signal and allows cleanup before the instance exits. A hard VM loss
  is detected when its message becomes visible again (up to 15 minutes).
- S3 archives `runs/<run-id>/` and `evals/<evaluation-id>/`. DynamoDB still serves the
  browser's report and log data. Recipe caches are synced to S3 between workers.
- Two new FIFO queues are created. The old standard queue and its DLQ are retained
  for migration; Terraform does not replace or purge them.

## Deploy using the operator profile

Run all commands from the repository root. The existing deployment uses
`AWS_PROFILE=operator`. Do not put profile credentials or secrets in Terraform.

Build and inspect the plan first:

```sh
npm --prefix web ci
npm --prefix web run build
AWS_PROFILE=operator terraform -chdir=infra init
AWS_PROFILE=operator terraform -chdir=infra plan \
  -var=enable_run_plane=true -var=runner_dispatch_enabled=true -var=runner_warm_pool=2
```

First provision with `runner_dispatch_enabled=false`, upload the tasks,
then enable dispatch and standby. For an existing fleet, first let its active evaluations
finish and stop legacy consumers before switching queues or replacing instances.
The task corpus is data and is **not** embedded in the Lambda or worker release.

```sh
AWS_PROFILE=operator terraform -chdir=infra apply \
  -var=enable_run_plane=true -var=runner_dispatch_enabled=false

# Obtain the destination with: terraform -chdir=infra output -raw runner_assets_bucket
AWS_PROFILE=operator python3 infra/upload-tasks.py \
  --bucket <runner-assets-bucket> --root ~/Desktop/harbor-tasks --all
```

You can replace `--all` with explicit taskset names for a limited staging setup.
Every task the hosted site offers must be uploaded before accepting real runs.
The worker downloads only the selected task, not the entire corpus.

Drain the legacy queue after the new FIFO queue exists and old consumers have stopped:

```sh
AWS_PROFILE=operator python3 infra/migrate-queue.py \
  --source <legacy_lease_queue_url> --target <lease_queue_url>
```

Those URLs are Terraform outputs. Migration keeps evaluation IDs, acknowledges
already finished jobs, and deletes an old message only after FIFO accepts it.
It refuses jobs still marked running or without a known owner. Review and settle
such legacy attempts before retrying; it never silently restarts them.

Then set `enable_run_plane=true`, `runner_dispatch_enabled=true`, and
`runner_warm_pool=2` in the deployment's
version-controlled configuration, review the plan, and apply. CI currently uses
variable defaults; a local ignored `terraform.tfvars` does not configure CI.
Deploy the matching frontend through the existing deploy workflow as well.

The initial lifecycle hook replaces the old Auto Scaling Group once; review that
replacement and settle legacy attempts before applying. Queue and report resources
are retained. Terraform ignores subsequent desired-capacity changes because the
controller owns them. Disabling dispatch stops new launches, lets protected workers
finish/retire, and disables standby replenishment.

Existing authoritative JOB rows from an earlier parallel release also need the new
active index before enabling dispatch: call `cloudqueue.update(eid, {})` for each
queued/running JOB. Legacy standard-queue migration calls enqueue and creates that
index automatically. Never infer runnable work from old public report rows alone.

## Build the prepared image

Packer creates a temporary image-builder EC2 instance, installs Docker, Python,
the analyzer CLI and common base images, creates a private AMI, and terminates the
builder on successful completion. It does not install app credentials or run user
jobs. Review cleanup if an image build is interrupted; the resulting AMI snapshots
continue to incur storage charges until removed.

```sh
cd infra
AWS_PROFILE=operator packer init runner-image.pkr.hcl
AWS_PROFILE=operator packer build runner-image.pkr.hcl
```

The checked-in default is `ami-07b3adfc7d225a1ea`, built and boot-tested on
2026-09-25 in this account's `us-west-2` region. For a new image, read the AMI ID
from `.build/runner-image-manifest.json` and set `runner_ami_id` in
the deployment configuration. An empty ID keeps a functional Ubuntu fallback that
performs installation once during standby preparation; the first cold launch is
therefore slower. Refresh the fleet after changing its image or release; ASG
refresh replaces active instances first, then the stopped pool.

## Worker credentials and bootstrap

Terraform uploads an immutable source ZIP to the private runner-assets bucket and
points the launch template at its content hash. The instance installs Docker,
Python dependencies and the Claude CLI, then launches `hr-agentd` under systemd.
The analyzer uses Bedrock through the instance role. `runner_model` and
`runner_analyzer_model` select model IDs; the account must have access to them.

The private GitHub clone key is read from the existing SSM parameter. It never
enters a queue or Terraform state. The proxy receives a renewable session for a
separate role with model invocation permissions only. Credentials are excluded
from archived logs. Harness and verifier containers cannot access EC2 metadata;
IMDSv2 keeps its hop limit of one and the host blocks forwarded metadata traffic.

Use Session Manager and `journalctl -u hr-agentd` for worker diagnostics. The
run attempt's console and events are also published to DynamoDB every two seconds.

## Verification

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
npm --prefix web run build
terraform -chdir=infra fmt -check
AWS_PROFILE=operator terraform -chdir=infra validate
terraform -chdir=infra test
```

The AWS integration test creates a temporary FIFO queue and DynamoDB table and
runs two **local Docker workers** using a local Git repository and fake model:

```sh
AWS_PROFILE=operator python3 tests/cloud_docker_smoke.py
```

It verifies AWS transactions, simultaneous claims, daily limits, cancellation,
expired/stale workers, owner checks, HTTP restart, actual Docker overlap and test
rewards. It deletes its temporary AWS resources and labelled Docker resources,
and retains diagnostic logs in the printed temporary directory. It does not
launch EC2, apply Terraform or call a cloud model. Prepared-image boot and direct EC2 stop/resume were measured separately as above.
The complete ASG lifecycle/S3/SSM path, application submit-to-worker latency and
real Bedrock availability still require a deployed smoke test.
