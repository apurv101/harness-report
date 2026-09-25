# harness-report

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

`/` opens the minimal “Evaluate your harness” landing page. `/#/connect` starts the GitHub flow;
`/#/runs` lists and searches actual local runs. `/#/runs/<run-id>` opens a run's trajectory, calls,
verifier, recipe, logs, and files. The selected tab is a `?tab=` query, so it survives a refresh.
Older `#runs/<id>` hashes and `/<run-id>` paths are rewritten to the current form on load.
`/api/runs`, `/api/run/<run-id>`, and `/raw/<run-id>/<file>` provide the underlying data.

**Runs from the site.** Served by `serve.py`, step 3's "Run task" is real: `evals.py` starts `run.sh` on the
chosen repository and the `aider_polyglot` bowling task, **one at a time** on this machine (a second start gets a
409 naming the running one). With `HR_EVENTS` set, `run.sh` appends one JSON line per stage, recipe decision, run
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

## Signing in with GitHub

`auth.py` gives `serve.py` a "Sign in with GitHub" flow built on one **GitHub App** — the same app both
identifies the user (user-to-server OAuth) and grants the repositories we may clone (installation tokens).
Recorded runs stay public either way — `/api/runs`, `/api/run/<id>` and `/raw/*` never ask who you are, because
the runs are the showcase.  Signing in gates only `/api/github/*`, which acts on the signed-in user's behalf.  `auth.py` reads `.env` the way
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
boot: served by `serve.py` the real flow takes over, and on the static Cloudflare Pages copy the call 404s and
the simulated preview stands.

`web/public/` holds `favicon.svg`, `robots.txt`, `sitemap.xml`, and `llms.txt`; the build copies them into
`web/dist` beside the page. The site is a Cloudflare Pages project named `harness-report` (Pages URL
`harness-report-927.pages.dev`; custom domains `harnessreport.com` and `www.harnessreport.com`). DNS for the
domain is the Route 53 zone in the `operator` AWS profile. Build, then deploy the build:

```sh
npm --prefix web run build
CLOUDFLARE_ACCOUNT_ID=49dbf7b45c8ebadc336657b6c73cbd8a npx -y wrangler pages deploy web/dist --project-name=harness-report --commit-dirty=true
```

`web/dist` is generated and git-ignored, so it has to be built before a deploy.
