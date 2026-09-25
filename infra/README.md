# infra

The whole hosted stack as Terraform, in one root module. `terraform apply` puts the site up;
`terraform destroy` takes it down. There is no second console step and no click-ops.

```sh
AWS_PROFILE=operator ./bootstrap.sh state    # once: the bucket Terraform keeps its state in
AWS_PROFILE=operator terraform init
AWS_PROFILE=operator terraform apply
AWS_PROFILE=operator ./bootstrap.sh secrets  # once more: the three values state is not allowed to hold
```

After that, pushing to `main` deploys. The first apply takes ~20 minutes, almost all of it the
certificate validating and CloudFront propagating; every apply after that is seconds.

## What it builds

```
harnessreport.com ─ Route 53 ─ CloudFront ─┬─ /*        S3  harness-report-site-<account>
                                  │        ├─ /api/*  ─┐
                                  │        ├─ /auth/* ─┼ Lambda  harness-report-api  (serve.py)
                                  │        └─ /raw/*  ─┘         │
                            edge function                        ├─ DynamoDB  harness-report
                            www→apex, SPA fallback                ├─ SSM       /harness-report/*
                                                                  └─ S3        …-runs, …-recipes
```

One origin, which is the point. The frontend calls `/api/...` as a relative path
([web/src/lib/api.ts](../web/src/lib/api.ts)) and `serve.py` has no CORS anywhere, so putting the
page and the API on one hostname is what lets both stay as they are.

| file | what |
|---|---|
| `site.tf` | the S3 bucket for `web/dist`, the distribution, its five behaviours |
| `edge.js` | the CloudFront function: www → apex, and extensionless paths → `/index.html` |
| `api.tf` | the Lambda, its package, its function URL, its secrets |
| `store.tf` | the DynamoDB table, the runs and recipes buckets, the two ECR repositories |
| `dns.tf` | the ACM certificate, its validation records, the A/AAAA aliases |
| `cicd.tf` | the GitHub OIDC provider and the role Actions assumes |
| `runplane.tf` + `runner-init.sh` | RUN-PLANE.md as infrastructure — **off by default**, see below |
| `bootstrap.sh` | the two things Terraform cannot do for itself |

## The API is serve.py

Not a port of it. [`lambda/handler.py`](../lambda/handler.py) turns the function URL event back into
the bytes of an HTTP request, hands them to `serve.H`, and turns what it wrote back into a response.
One routing table, and `python3 serve.py` stays the way to reproduce anything the site returns.

Terraform zips the package itself out of `serve.py`, `auth.py`, `evals.py` and `lib/*.py`, so there
is no build step for the API and no artifact to keep in sync — an apply ships whatever is committed.

Three things differ from the laptop, all of them environment:

| variable | why |
|---|---|
| `HR_SESSIONS=ddb` | sessions are rows, not `.auth/sessions.json`. Lambda has no disk to share between instances, and the package directory is read-only anyway |
| `HR_EVALS=queue` | accepts jobs into SQS FIFO; EC2 workers own Docker |
| `HR_PUBLIC_HOST` | CloudFront cannot forward the viewer's `Host` to a function URL origin, so it is configured — and the edge function collapses www into the apex so one configured value is right for every request |

`/raw/<run-id>/<file>` is answered by the Lambda out of the text the store inlines into each row, so
it works before the runs bucket holds anything. When `hr-agentd` starts syncing folders to S3, that
behaviour moves to an S3 origin and the Lambda stops seeing it.

## Why the function URL is not behind OAC

OAC is the tighter answer and it does not fit. With OAC on a Lambda function URL, CloudFront signs
the request but not the body, so **the browser** has to compute the SHA-256 of every POST and send
it as `x-amz-content-sha256` — CloudFront's signing scheme, in the frontend, forever.

Instead the function URL is `NONE` with a random 48-character id, and CloudFront adds an
`x-hr-origin` header holding a 48-character secret that `handler.py` checks before it parses
anything. Two unguessable values, no signing in the page. The secret lives in Terraform state and
rotates by tainting `random_password.origin`.

## Secrets

Three values never enter Terraform state or git: `GITHUB_CLIENT_SECRET`, `SESSION_SECRET` and the
app's private key. **Terraform does not manage them at all** — `./bootstrap.sh secrets` creates the
SecureStrings and fills them from `../.env`, and `handler.py` reads them at cold start. Missing or
holding `unset`, they are treated as absent, so a stack whose secrets have not been filled in serves
the runs read-only instead of failing to boot.

The first version *did* manage them, empty, with `ignore_changes = [value]`. CI proved that wrong:
Terraform refreshes every resource it manages, so every plan called `ssm:GetParameter`, which the
deploy role explicitly denies. `ignore_changes` governs what Terraform does with a diff, not whether
it reads. Managing them and forbidding CI to read them cannot both be true; not reading them won.
The cost is that `terraform destroy` leaves the three parameters behind — the right default for
something a person put there by hand.

The GitHub App's client id and app id are public identifiers and are ordinary variables.

The deploy role carries an explicit `Deny` on reading those parameters. CI writes infrastructure; it
has no business reading a session secret.

## CI/CD

| workflow | on | what |
|---|---|---|
| [`plan.yml`](../.github/workflows/plan.yml) | pull request | typecheck and build the frontend, compile the Python on 3.13, `fmt -check`, `validate`, and post the plan on the PR |
| [`deploy.yml`](../.github/workflows/deploy.yml) | push to `main` | build → apply → sync → invalidate → curl the site and `/api/runs` through CloudFront |
| [`destroy.yml`](../.github/workflows/destroy.yml) | manual, types the domain | `terraform destroy` with `allow_data_destroy=true` |

No keys anywhere: GitHub mints an OIDC token, AWS trades it for `harness-report-deploy`, and it
expires with the job. One repository variable is needed —

```sh
gh variable set AWS_DEPLOY_ROLE --body "$(terraform output -raw deploy_role_arn)"
```

The sync is two passes on purpose: hashed bundles go up first with a one-year immutable
`Cache-Control`, then `index.html` and the crawler files with `max-age=0`. A browser never fetches a
page that points at bundles the bucket does not have yet.

## The run plane

The worker now runs the same isolated Docker pipeline as the local pool. SQS FIFO
serializes jobs per GitHub user and permits different users in parallel. DynamoDB
transactions own job state; the API no longer rejects every submission while one
job is active. A Lambda controller wakes EC2 capacity on submission and returns it
to zero afterward. `runner_max_size` bounds parallel evaluations; `runner_warm_pool`
sets the number of unused, stopped standby workers.

See [CLOUD.md](../CLOUD.md) for architecture, operator-profile deployment commands,
task upload, migration from the retained standard queue and integration tests.
Provision the assets with dispatch disabled, upload the task corpus, then enable
`runner_dispatch_enabled`. The fleet remains opt-in through `enable_run_plane`.
`runner-image.pkr.hcl` builds the prepared AMI; `scaler.tf` owns demand dispatch and
reconciliation. Stopped workers retain Docker layers on encrypted EBS.

## Pulling it down

`terraform destroy` — or the destroy workflow, which makes you type the domain.

What survives, deliberately: the Route 53 **zone** (looked up, never managed here), the state bucket
(`bootstrap.sh` made it), and the GitHub App.

What goes: everything else, including the runs and recipes buckets, but only when
`allow_data_destroy=true` is passed. An ordinary apply cannot make those two disposable, which is
why the flag exists and why it is not in `terraform.tfvars.example`.

The DynamoDB table now also holds authoritative cloud jobs and daily limits, alongside the derived report index. Back up this state; syncing run folders does not recreate pending jobs. The buckets are the only thing here that is not reproducible from the
repo.

## Costs

CloudFront's free tier is 1 TB and 10M requests a month, permanently, and 70 runs is 619 MB. Lambda,
DynamoDB on-demand and the two small buckets are pennies. The bill is the Route 53 zone at $0.50/mo
until the run plane turns on — at which point it is warm EC2 capacity and the analyzer, exactly as
RUN-PLANE.md says.
