# Parallel evaluations on one machine

The browser submits jobs to `serve.py`. In `HR_EVALS=local-queue` mode, the server
records each job in a durable SQLite queue and immediately returns its ID. A
separate `hr-local` process claims jobs and launches `run.sh` in parallel. Docker
runs a separate sandbox and model proxy for every job. DynamoDB Local holds the
results used by the existing browsing pages; it does not schedule jobs.

No SQS, cloud API, or cloud worker is involved. Ordinary harness evaluations still
use the model configured in `.env`, and a missing recipe invokes the Claude CLI.
The Docker smoke test below replaces both with local fixtures.

## Start

Requirements: Docker, Python 3.11+, Node/npm, Git, and (for real harness recipes)
the authenticated Claude CLI. The Harbor task corpus must be available under
`HARBOR_TASKS` (default `~/Desktop/harbor-tasks`). Keep `HR_DDB=local` in `.env`.
Exported environment variables now take precedence over `.env` in both Python
and `run.sh`.

```sh
cd /Users/aj/Desktop/harness-report
./run.sh ddb start
npm --prefix web ci
npm --prefix web run build
```

Terminal 1 — HTTP server with explicitly enabled local test identities:

```sh
HR_EVALS=local-queue HR_DDB=local HR_LOCAL_USERS=1 python3 serve.py --port 8790
```

Terminal 2 — two worker slots, at most one running job per user:

```sh
./hr-local --workers 2 --per-user 1
```

Open <http://localhost:8790/connect>. Choose Alice in one browser profile and Bob
in another (or a normal and a private browser window). These test identities are
available only with **both** `HR_EVALS=local-queue` and `HR_LOCAL_USERS=1`; they
replace GitHub authentication for this localhost server and support public repos.
Without `HR_LOCAL_USERS`, the existing GitHub login is used.

Submit a task from each account. Both can run together, including on the same
repository. Additional jobs wait. Each account's **Your evaluations** page lists
its queued, running and completed jobs. An account can view its evaluation
progress and cancel its own jobs; another account cannot operate on them.
Completed run reports remain public, as they are elsewhere in this app.

`./hr-local --workers 4 --per-user 2` allows four simultaneous evaluations, with
at most two per user. Each executing agent normally has two containers: its
sandbox and its proxy. Build/check containers are temporary additional work.
`--workers` limits whole evaluations, including preparation and verification.

For Vite development, use API port 8789 because `web/vite.config.ts` forwards
requests there. The built frontend can be served from any `--port`.

## Queue and isolation

- `evals/queue.sqlite3` is the authoritative local job state. SQLite transactions
  atomically accept capped submissions, claim jobs and record cancellation.
- Jobs have random IDs even when the same repository is submitted in the same second.
- The oldest eligible job is claimed; a user already at their limit does not
  prevent another user's job from starting.
- A process lock permits only one worker pool per queue, so accidentally starting
  another `hr-local` cannot double its concurrency limit.
- `work/jobs/<evaluation-id>/<harness>/` contains a private checkout and build files.
  Every job gets separate image tags, containers and Docker networks. Shared recipe
  cache writes are atomic. Docker still reuses identical build layers.
  Recommendation refreshes for the same harness are serialized as well.
- Logs and results remain in `evals/<id>/` and `runs/<id>-<task>/`. Local publication
  of derived harness/task summaries is serialized to avoid competing writers.
- Cancelling a waiting job prevents it from starting. Cancelling an active job
  stops its process group and cleans only Docker resources labelled with its ID.
- Restarting the HTTP server does not interrupt workers or lose queued jobs.
  Stopping workers terminates active attempts; waiting jobs survive. On a worker
  restart, interrupted attempts are cleaned and marked failed rather than silently
  repeated (which could repeat paid model calls). Submit a new job to retry.

Use the same absolute `HR_DATA_DIR` for server and workers to keep queue, workspaces and
results in a different directory. Use the same `HR_TABLE` for both when selecting
a different DynamoDB Local table. Local queue mode refuses non-loopback DynamoDB
endpoints. `HR_DAILY_CAP` remains a per-user submission limit (default 5; `0`
disables it for local experiments).

```sh
./hr-local --status
```

Stop the HTTP server and workers with Ctrl-C in their respective terminals.
`./run.sh ddb stop` stops the database while retaining its data. Per-job image tags
are retained for inspecting provenance and reusing build layers; they carry the
`hr.evaluation` label. Containers and networks are cleaned after each job.

## Verification

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
npm --prefix web run build
```

The integration test requires Docker and DynamoDB Local on port 8001:

```sh
python3 tests/local_docker_smoke.py
```

It uses a temporary application copy, a local Git repository, a local fake model
endpoint and a temporary DynamoDB table. It exercises simultaneous users on the
same repository, two actual overlapping Docker sandboxes, per-user limits, queued
and running cancellation, owner checks, an HTTP restart, verifier rewards and model
call recording, worker crash recovery and worker-pool exclusivity. It never invokes a cloud model or the recipe analyzer. Docker may
download image layers or proxy dependencies. The temporary table and labelled
Docker resources are removed; the printed temporary directory retains diagnostic logs.
