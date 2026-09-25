# harness-report

For a local queue with multiple users and parallel Docker evaluations, see
[LOCAL.md](LOCAL.md). Start `serve.py` with `HR_EVALS=local-queue` and run
`./hr-local --workers 2 --per-user 1` alongside it.

One command. Give it a GitHub repo that contains an AI agent harness and a task; it downloads the repo,
has an AI write a Docker overlay for it, builds the sandbox, puts a recording proxy between the harness
and the model, and runs the task. Every model call the harness makes is captured on the wire, in one
format, whatever the harness is. Give it a Harbor taskset instead of a task text and it runs the chosen
tasks inside their own task images, runs each task's verifier, and records the reward.

```sh
./run.sh https://github.com/SWE-agent/mini-swe-agent "Create /work/fizzbuzz.py that prints FizzBuzz for 1 to 15 and run it."
./run.sh https://github.com/SWE-agent/mini-swe-agent --taskset aider_polyglot --tasks polyglot_python_bowling
./run.sh https://github.com/SWE-agent/mini-swe-agent --taskset aider_polyglot --grep python --limit 20 -k 3
./run.sh tasks aider_polyglot --grep python                # list tasks in a taskset
./run.sh runs                                              # list the runs (one folder each under runs/)
./run.sh view runs/<run-id>                                # the recorded calls as a conversation
./run.sh <url> "<task>" --rebuild                          # regenerate the recipe and overlay for this repo
./run.sh <url> --taskset aider_polyglot --tasks t --model bedrock/<id>   # override MODEL from .env for this invocation
```

Files: `run.sh` (the CLI and the stage spine), `lib/` (the stages), `proxy.py` (the recorder), `.env` (MODEL,
AWS_PROFILE, AWS_REGION; optional ANALYZER_MODEL and HARBOR_TASKS, default `~/Desktop/harbor-tasks`).

`run.sh` holds the usage message, the arguments and the order the stages run in; each stage is one file in
`lib/`, sourced in that order. Everything a stage prints for a person, and everything it writes into a run
folder, is Python beside it — so the shell stays the plumbing and the formats stay readable.

| | |
|---|---|
| `lib/common.sh` | `emit` (the `HR_EVENTS` stream), `die`, `help`, `stage`, `with_timeout`, `PRELUDE`, the image lookups |
| `lib/harbor.sh` | where a taskset lives, what a `task.toml` says, which tasks a run selects, the task's own image |
| `lib/report.sh` | the read-only subcommands: `tasks`, `runs`, `view`, and the end-of-sweep table |
| `lib/fetch.sh` | stage 1 — the harness repo at its current HEAD, private repos included |
| `lib/recipe.sh` | stages 3 and 4 — `analyze`, the per-commit recipe store, `build_overlay`, `check_image` |
| `lib/proxy.sh` | stage 5 — the `hr-proxy` image, the two networks, one proxy container per run, the phase switch |
| `lib/execute.sh` | stage 6 — `run_one`: the agent, then the verifier, then the run's result |
| `lib/analyze-prompt.md`, `lib/recipe-schema.json` | what the analyzer is asked, and the shape it must answer with |
| `lib/report.py` | the `runs` table, the `view` conversation, the task × k reward table |
| `lib/recipe.py` | validate the analyzer's output, read fields, hash, env substitution, the diff against the previous recipe |
| `lib/runjson.py` | `run.json` in three passes: origin, provenance, result |
| `lib/task.py`, `lib/events.py` | a `task.toml` as one line; one `HR_EVENTS` event as one line |

## Stages

| stage | what happens | leaves behind |
|---|---|---|
| fetch | shallow `git clone` | `work/<name>/repo/` |
| select | (Harbor mode) resolve the taskset and the chosen tasks, skip multi-container ones, build the first task image | image `hr-task/<taskset>:<task>` |
| analyze | `claude -p` reads the repo and returns a recipe as JSON: an overlay Dockerfile (`ARG BASE` / `FROM ${BASE}`) that installs the harness self-contained under `/opt/harness`, the env that points the harness at the proxy, the command that runs one task from `$TASK`, a check command, and a fallback base image | `work/<name>/recipe.json`, `Dockerfile`, `run-harness` |
| build | `docker build` of the overlay FROM the fallback base and, in Harbor mode, FROM the first task image; the check command runs in both with no network; a failure is fed back to the AI, three tries | images `hr-<name>` and `hr-<name>/<taskset>:<task>` |
| proxy | `proxy.py` in its own container on the `hr-net` network with `~/.aws` mounted read-only; the harness container never holds credentials | |
| run | the sandbox runs the task with the recipe's env, cwd = the task's working directory; the proxy appends every call to `calls.jsonl` | `runs/<run-id>/` |
| verify | (Harbor mode) `tests/` is copied into the same container only after the agent finishes, `tests/test.sh` runs, `reward.txt` is read | `runs/<run-id>/verifier/` |

The recipe is reused on the next run of the same repo, so the AI runs once per harness. Overlay images are
cached per harness x task image.

## Harbor tasks

The task owns the container: `<task>/environment/Dockerfile` (or `task.toml`'s `docker_image`) is the base,
the harness overlay is built on top of it, `instruction.md` becomes `$TASK`, the agent runs with cwd = the task
image's `WORKDIR`, then `tests/test.sh` writes `/logs/verifier/reward.txt`. Budgets (`agent`/`verifier`
`timeout_sec`, `cpus`, `memory`) come from `task.toml`. Multi-container tasks (docker-compose) are skipped.
Nothing in the task image changes except what the overlay adds under `/opt/harness`; the harness itself is
never modified.

A taskset is a directory of task folders, given as a path or a name under `$HARBOR_TASKS/{datasets,hub-datasets}`.
Pick tasks with `--tasks a,b`, `--grep re`, `--limit N` or `--all`; `-k N` repeats each task N times so pass^k
and flip rate exist. Each task x k is its own run folder, and the invocation ends with a task x k reward table.

The tests run the way Harbor runs them: on an open network with none of the agent phase's proxy settings, so a
task's own network assertions are not answered by the proxy (verify-phase traffic is therefore not in
`egress.jsonl`).

**The oracle gate.** `./run.sh oracle <taskset> a,b` runs each task's `solution/solve.sh` in place of an agent —
same image, same `tests/test.sh`, no proxy, no model — and appends the reward to `catalog/oracle.jsonl`. The site
only offers tasks that are candidates in `catalog/runnable.json` *and* whose newest oracle result is 1: a task
whose reference solution fails its own tests (aider_polyglot `polyglot_java_pov`, algotune
`algotune-vectorized-newton`) would mark every harness as failing.

**The corpus in the table.** `./run.sh ddb sync --tasks` publishes all ~93.5k tasks in `$HARBOR_TASKS`
(`TASK-INDEX.json`, each `task.toml` and `instruction.md`), joined to `catalog/index.jsonl` for domain, owner and
grading (`lib/tasks.py`), as taskset and task rows — the site has no disk, so a task page is only what the table
holds. Each finished run folds itself into its task's `results` and its harness card.

## The proxy

`proxy.py` speaks the OpenAI chat-completions API and the Anthropic messages API on the harness side (tool
calling and streaming on both). Each call is routed by the model name the harness sends:

```sh
# .env or --routes: pattern=target, first match wins; MODEL serves everything else
ROUTES='claude-haiku*=anthropic,gpt-4o-mini=openai/gpt-4.1-mini'
```

| target | goes to | model |
|---|---|---|
| `bedrock/<id>` (or a bare id) | Bedrock through `~/.aws` | `<id>` |
| `anthropic` / `anthropic/<id>` | api.anthropic.com with `ANTHROPIC_API_KEY` | as requested / `<id>` |
| `openai` / `openai/<id>` | `OPENAI_BASE_URL` (default api.openai.com) with `OPENAI_API_KEY` | as requested / `<id>` |

So a harness can keep its own models on the real provider with our key, swap some of them, or send everything to
one Bedrock model (the default: no ROUTES, `MODEL=bedrock/...`). The key the harness holds is a dummy; the proxy
drops it and uses its own. `anthropic` and `openai` targets only take requests in their own API shape; Bedrock takes
both. Upstream is always asked for a finished response and the stream the harness wants is synthesized from it.
Each call becomes one JSON line: request, response, tokens, latency, the model requested, the backend and model
that served it, and any error. `run.json` sums the calls per requested/served pair under `models`.

## A run folder

Every run is one top-level folder, `runs/<run-id>/`, where `<run-id>` is the timestamp (or `--run-id`) plus
`-<task>` and `-k<i>` for a Harbor task. The folder is self-describing:

| file | what |
|---|---|
| `run.json` | the config: where the run came from and how it ended (below) |
| `task.txt` | the prompt text, or the Harbor task's `instruction.md` |
| `command.sh` | the recipe's run command |
| `recipe.json` | the harness recipe used |
| `calls.jsonl` | every model call, written by the proxy (the trajectory) |
| `stdout.log`, `stderr.log`, `proxy.log` | the harness's output and the proxy's log |
| `verifier/` | Harbor only: `stdout.log`, `stderr.log`, `reward.txt` from `tests/test.sh` |
| anything else | written by the harness itself to `/out` (e.g. its own trajectory file) |

`run.json` is written in two halves. The origin goes in before anything runs, so a run that dies mid-way still
says what it was: `kind` (`prompt` or `harbor`), `harness` (`name`, `repo`, `commit`, `api_style`), `task`
(`name`, `taskset`, `taskset_dir`) or `prompt`, `model`, `workdir`, `run_command`, `started`. The result is
merged in at the end: `finished`, `rc`, `seconds`, `reward` (null for a prompt run), `verifier_rc`, `calls`,
`input_tokens`, `output_tokens`, `errors`, `files`. `./run.sh runs` prints one line per folder from these.

## The run store (DynamoDB)

The run folder is the record; the table is that record as rows, so a screen can ask for the one piece it draws
instead of the server walking 600 MB of folders on every request. One table, generic `pk`/`sk`, the same
single-table shape the accounting harness uses — `lib/store.py` is the only place a key is built, and its
docstring is the schema.

```bash
./run.sh ddb start          # DynamoDB Local in docker on :8001, and create the table
./run.sh ddb sync           # every run folder, recipe and evaluation → rows (12 s for 68 runs, 4,000 rows)
./run.sh ddb status         # what is in it
./run.sh ddb run <run-id>   # read one back as JSON, exactly as /api/run/<run-id> serves it
```

| pk | sk | what |
|---|---|---|
| `RUNLIST` | `RUN#<run-id>` | the run card: all of `run.json`, the test tally, the last tool call |
| `RUN#<run-id>` | `META` | the same card, for a read that already knows the run id |
| `RUN#<run-id>` | `CALL#<0000000001>` | one model call, field for field as the proxy recorded it |
| `RUN#<run-id>` | `EGRESS#<0000000001>` | one outbound connection the sandbox made |
| `RUN#<run-id>` | `FILE#<path>` | one file in the folder: its size, and its text when it is text and small |
| `RUN#<run-id>` | `MANIFEST`, `TESTS` | every file with its size; the per-test breakdown with sources and tracebacks |
| `RECIPELIST`, `RECIPE#<name>@<commit>` | `RECIPE#…`, `META` | the recipe card, and the recipe itself |
| `EVALLIST`, `EVAL#<eval-id>` | `EVAL#…`, `META`, `EVENT#<n>` | an evaluation started from the site, with its stage events and console log |

Index `harness` answers "every run and every recipe of one harness" in one query
(`./run.sh ddb harness aider-ai-aider`).

Three rules, all of which the sibling repo learned the hard way. **No `UpdateItem`** — one writer owns a
partition, so rows are re-put whole and a deployment needs only Query/GetItem/PutItem/BatchWriteItem.
**The index row carries the whole card**, so the runs page renders from one Query. **Sequence sort keys are
zero-padded**, and `META`/`MANIFEST`/`TESTS` sort outside those ranges, so `begins_with(sk, "CALL#")` can never
sweep up the metadata.

Big things stay files. A run folder can be 150 MB (one harness shipped a whole Node install into `/out`) and a
DynamoDB item is capped at 400 KB, so a row holds every *fact* about the run plus the text of the files a person
reads, inlined up to 200 KB; past that it keeps the head and the tail and says `truncated`, and the whole file is
still at `/raw/<run-id>/<file>` — in S3 once runs land there ([RUN-PLANE.md](RUN-PLANE.md)). Two runs out of 68
have a log cut this way, and two have more than 1,000 files.

`run.sh` publishes the card before the agent starts and the whole run when the verifier is done, `recipe.sh`
publishes a recipe when it saves one, and `evals.py` publishes an evaluation on every status change — all of them
best-effort: if the table is not there the run folder is still written, and the run does not fail. `serve.py`
serves `/api/runs` and `/api/run/<id>` from the table when one answers and from the folders when it does not, with
byte-identical JSON either way (`--store table|files|auto`); its boot line names which. Nothing points at a table
unless `HR_DDB`, `HR_DDB_ENDPOINT` or `HR_TABLE` is set, `.env` carries `HR_DDB=local`, and every command that
touches it prints the table it used — the sibling repo spent two sessions believing its local switch was on while
every write went to production.

The table is a derived index: `./run.sh ddb reset && ./run.sh ddb start && ./run.sh ddb sync` rebuilds every row
from the folders. `lib/ddb.py` speaks the DynamoDB wire protocol (SigV4 and all) in the standard library, so the
same code reaches the laptop's container and a real table in a region with no boto3 anywhere.

## First run (2026-09-22)

mini-swe-agent at 04d809c on Bedrock Sonnet 4.5, FizzBuzz: analyze 7 turns, $1.59, 122 s; build + check
~70 s; task 21 s, 6 calls through the proxy, 0 errors, harness exit 0. The AI chose litellm's `openai/`
route with `OPENAI_BASE_URL` pointed at the proxy and the model name `gpt-4o`, which the proxy swapped.

## Frontend

`web/` is the single frontend: a React + TypeScript app (Vite) covering the landing page, the GitHub
onboarding preview, and the real recorded evaluations, with one shared navigation and design.
`npm run build` writes `web/dist`, which `serve.py` serves together with the read-only `runs/` API.
Python still has no dependencies; the frontend is the only thing that needs a build.

```sh
npm --prefix web install                    # once
npm --prefix web run build                  # writes web/dist
python3 serve.py                            # http://localhost:8789
python3 serve.py --port 9000 --runs /path/to/runs --dist /path/to/dist

npm --prefix web run dev                    # http://localhost:5173, /api + /auth + /raw proxied to :8789
npm --prefix web run typecheck              # tsc --noEmit, also part of build
```

`/` opens the minimal “Evaluate your harness” landing page. `/connect` starts the GitHub flow;
`/runs` lists and searches runs, and `/runs/<run-id>` opens a run's trajectory, calls, verifier, recipe, logs,
and files (the tab is a `?tab=` query). `/harnesses/<name>` is one harness — what it is for, results per task,
its runs, and the tests recommended next; `/tasks`, `/tasks/<taskset>` and `/tasks/<taskset>/<task>` browse the
Harbor corpus with every harness's results. Routes are real paths (BrowserRouter); older `#/…` and `#runs/<id>`
hashes and `/<run-id>` paths are rewritten on load.

**For agents and crawlers** (`lib/pages.py`, `lib/mcp.py`). Every harness, taskset, task and run page is served
by `serve.py` with its own `<title>`, description and canonical, plus a `<noscript>` Markdown copy; add `.md` or
`.json` to any of those URLs for the Markdown or the object. `/llms.txt` (and `/llms-full.txt`) index the site
for LLMs, `/sitemap.xml` is a sitemap index with one sitemap per taskset, and `POST /mcp` is a read-only MCP
server (streamable HTTP, stateless) with `search_tasks`, `get_task`, `list_tasksets`, `list_harnesses`,
`get_harness`, `get_run`, `recommend_tasks` and `run_url` — starting a run stays behind GitHub sign-in.

**What to run next** (`lib/recommend.py`). Before a first run, the task is picked by rules from the repo's GitHub
language and description (`GET /api/first-task`). After every finished run, the runner profiles the harness once
per commit (`claude -p` with only Read/Glob/Grep, cached in `profiles/<name>@<commit>.json`) and ranks the
runnable pool for it with a model (`RECOMMEND_MODEL`, default haiku; the rules when that fails), written as
`HARNESS#<name>/RECS`. The result page polls for them and each one starts with one click. `HR_DAILY_CAP`
(default 5) caps evaluations per login per day.

**Runs from the site.** Step 3's "Run task" is real, and `HR_EVALS` decides who does the work:

| `HR_EVALS` | what `POST /api/evals` does | who sets it |
|---|---|---|
| `on` (default) | start `run.sh` here and follow the folder | `python3 serve.py` on a laptop |
| `local-queue` | enqueue on disk; `hr-local` runs multiple isolated Docker evaluations | local multi-user testing; see [LOCAL.md](LOCAL.md) |
| `queue` | record the evaluation, put a lease on SQS, report from the table | the hosted API, which has no Docker daemon |
| `off` | refuse, with a reason | — |

In queue mode [`hr-agentd`](hr-agentd) is the other half: it leases from the queue, runs the same `run.sh`, and
republishes the record as it goes, so a page polling the hosted API sees stages, console output and the live
call count while they happen. The queue is the entire coupling — the API never learns where a run happens and
the runner never learns who asked — which is what lets the runner sit on a laptop today and on an EC2 runner
later without either side changing ([RUN-PLANE.md](RUN-PLANE.md)).

```sh
export HR_QUEUE_URL=$(terraform -chdir=infra output -raw lease_queue_url)
export HR_TABLE=harness-report HR_DDB= AWS_PROFILE=operator
./hr-agentd --status      # what is queued, and what the table thinks is running
./hr-agentd               # lease and run, forever
```

`AWS_PROFILE` is the daemon's own credentials, for the queue and the table. `HR_RUN_PROFILE` is the profile the
*model* call uses when it differs — unset, `run.sh` reads it from `.env`, which is also what an EC2 runner wants
since there the instance role is both. Without that split the daemon's profile is inherited into `lib/proxy.sh`,
which forwards it to the proxy container, and every model call goes out as the control plane.

The original `on` and cloud `queue` modes reject another active evaluation with a 409. The cloud check is a
query followed by a write, so it is not an atomic concurrency guarantee. `local-queue` accepts independent
jobs and limits execution in its worker pool. With `HR_EVENTS` set, `run.sh` appends one JSON line per stage, recipe decision, run
folder, result and error; the page polls `GET /api/evals/<id>?after=<n>` every 1.5 s for those events plus the live
model-call count read from the run's `calls.jsonl`, then shows the real result. A private repository is cloned with a
short-lived GitHub App installation token that reaches git only through its environment. Cancel sends SIGTERM to
the run's process group, and `run.sh` removes its containers on the way out. Each evaluation keeps `eval.json`,
`events.jsonl` and `console.log` in `evals/<id>/`; the run itself is an ordinary `runs/<id>-<task>/` folder. Without
GitHub sign-in configured, sign-in stays simulated but runs are still real; on the static site both are simulated.

```
web/
  index.html                 the page shell: metadata, fonts, <div id="root">
  public/                    favicon.svg, robots.txt, sitemap.xml, llms.txt — copied into dist as-is
  src/
    main.tsx  App.tsx        boot, providers, HashRouter
    router/                  routes, the flow's guards, and the legacy-link rewrite
    pages/                   one file per route: landing, sign-in, import, check, result, runs, run detail
    components/
      layout/                header, footer, preview banner, the shell every page renders into
      landing/               hero, the example report, the three steps
      onboarding/            flow sidebar, repository picker, check stages
      runs/                  run table, status pills, fact grids, tabs/ (trajectory, calls, verifier, …)
      ui/                    icons, pills, facts, clipped text, search box, empty card
    state/                   SessionContext (/api/me), PreviewContext (the simulated onboarding)
    hooks/                   document title, aborting JSON loads, the simulated run's timers
    lib/                     api client, formatting, run types, conversation parsing, tooltip text
    styles/                  tokens → base → layout → ui → landing → onboarding → responsive → runs → character
```

The stylesheets are imported in that order by `styles/index.css`, and the order matters: `character.css`
is the riso layer that overrides the structure above it.

GitHub sign-in and the onboarding task remain explicitly simulated. Recorded evaluations use the real
contents of `runs/`. A plain static host can display the frontend, but needs the run API to load evaluations.

## Hosting

Everything is AWS, in the `operator` account, and all of it is [`infra/`](infra/) — one Terraform root
module that stands the stack up and takes it down. The site was on Cloudflare Pages until 2026-09-24; it
moved because the frontend calls `/api/...` as a relative path and `serve.py` has no CORS, so the page and
the API want one origin, and because `/raw/<run-id>/<file>` is S3 objects sitting next to the table the rest
of the API reads.

```
harnessreport.com ─ Route 53 ─ CloudFront ─┬─ /*                    S3      web/dist
                                           ├─ /api/* /auth/* /raw/* Lambda  serve.py
                                           │                                ├─ DynamoDB  the run store
                                           │                                └─ S3        runs, recipes
                                           └─ edge function: www → apex, SPA fallback
```

The Lambda **is** `serve.py`: [`lambda/handler.py`](lambda/handler.py) turns the function URL event back
into the bytes of an HTTP request, lets `serve.H` answer it, and turns what it wrote back into a response.
Terraform zips the package out of the repo's own files, so there is no build step for the API and an apply
ships whatever is committed. Three environment variables are all that differ from the laptop: `HR_SESSIONS=ddb`
(sessions are rows — Lambda has no disk to share), `HR_EVALS=queue` (SQS FIFO hands jobs to EC2 workers)
and `HR_PUBLIC_HOST`.

```sh
AWS_PROFILE=operator infra/bootstrap.sh state      # once: the state bucket
AWS_PROFILE=operator terraform -chdir=infra init
AWS_PROFILE=operator terraform -chdir=infra apply
AWS_PROFILE=operator infra/bootstrap.sh secrets    # once: the values state is not allowed to hold
```

After that, pushing to `main` deploys: build → `terraform apply` → sync `web/dist` → invalidate → curl the
page and `/api/runs` through CloudFront. Pull requests get a typecheck, a build, `terraform validate` and the
plan as a comment. Credentials are OIDC, so CI holds no keys. `infra/README.md` has the rest — why the
function URL is not behind OAC, where the secrets live, and what a destroy does and does not delete.

The EC2 runner fleet from [RUN-PLANE.md](RUN-PLANE.md) is in `infra/runplane.tf` behind
`enable_run_plane`. See [CLOUD.md](CLOUD.md) for task upload, queue migration and worker activation.

## Signing in with GitHub

`auth.py` gives `serve.py` a "Sign in with GitHub" flow built on one **GitHub App** — the same app both
identifies the user (user-to-server OAuth) and grants the repositories we may clone (installation tokens).
Recorded runs stay public either way — `/api/runs`, `/api/run/<id>` and `/raw/*` never ask who you are, because
the runs are the showcase.  Signing in gates repository access and cloud evaluation submission. Evaluation progress and cancellation are scoped to the owner.  `auth.py` reads `.env` the way
`run.sh` does, so the variables can live there; anything already in the environment wins.

```sh
GITHUB_CLIENT_ID=Iv23li... GITHUB_CLIENT_SECRET=... SESSION_SECRET=$(openssl rand -hex 32) \
BASE_URL=https://app.harnessreport.com python3 serve.py
```

| route | what |
|---|---|
| `/auth/github` | 302 to GitHub with a signed state nonce in a cookie |
| `/auth/callback` | checks the nonce, trades the code for a token, reads `/user`, sets the session cookie |
| `/auth/logout` | drops the session |
| `/api/me` | `{auth, user, install_url, can_clone}` — what the frontend boots from |
| `/api/github/installations`, `/api/github/repos?installation=<id>` | the repositories the user granted (401 when signed out) |

The browser only ever holds a signed session id (`HttpOnly`, `SameSite=Lax`, `Secure` on https); the GitHub
tokens stay server-side in `.auth/sessions.json` (0600). `GITHUB_APP_ID` + `GITHUB_APP_KEY` add
`auth.clone_token(installation_id)`, a ~1 h token for `git clone https://x-access-token:<token>@github.com/...`;
the app JWT is signed by `openssl`, so the no-dependency promise holds. The frontend asks `/api/me` on
boot: served by `serve.py` the real flow takes over, and on a static copy with no API behind it the call 404s
and the simulated preview stands.

`web/public/` holds `favicon.svg`, `robots.txt`, `sitemap.xml`, and `llms.txt`; the build copies them into
`web/dist` beside the page. `web/dist` is generated and git-ignored, so it has to be built before a deploy —
which the deploy workflow does, so nobody has to remember.

For on-demand AWS workers, stopped standby, prepared images, queue migration and deployment checks, see [CLOUD.md](CLOUD.md).
