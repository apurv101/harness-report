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

Files: `run.sh` (the pipeline), `proxy.py` (the recorder), `.env` (MODEL, AWS_PROFILE, AWS_REGION; optional
ANALYZER_MODEL and HARBOR_TASKS, default `~/Desktop/harbor-tasks`).

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
calling and streaming on both) and Bedrock on the model side. Whatever model name the harness sends is
recorded and replaced with `MODEL` from `.env`. Each call becomes one JSON line: request, response, tokens,
latency, the model requested, the model used, and any error.

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

## First run (2026-09-22)

mini-swe-agent at 04d809c on Bedrock Sonnet 4.5, FizzBuzz: analyze 7 turns, $1.59, 122 s; build + check
~70 s; task 21 s, 6 calls through the proxy, 0 errors, harness exit 0. The AI chose litellm's `openai/`
route with `OPENAI_BASE_URL` pointed at the proxy and the model name `gpt-4o`, which the proxy swapped.

## Run viewer

`ui/` is a separate, read-only web UI for the `runs/` folder: one Python server (no dependencies) and one page.

```sh
python3 ui/serve.py                         # http://localhost:8788   (--port, --runs to change)
```

`/` lists every run. `/<name>/<run-id>` (or just `/<run-id>`) shows one run: the header facts from `run.json`,
the task, and tabs for the trajectory (the conversation from any recorded call, last by default, with tool calls
and observations), the calls table (click a row for the raw request and response), the recipe (summary, run and
check commands, env, Dockerfile, notes), the verifier (Harbor: reward, the task's test counts parsed from pytest's
`-v` output with the failed test names, and the test.sh logs; tests from files the agent wrote itself are shown
separately as `+N own`), the logs (`stdout.log`, `stderr.log`, `proxy.log`), and every file in the
run folder with a raw link. `/api/run/<name>/<run-id>` returns the same data as JSON.

## Site

`site/` is harnessreport.com: one self-contained `index.html` (inline CSS, no build, same skeleton as the
ninesweep.com page), `favicon.svg`, `robots.txt`, `sitemap.xml`, `llms.txt`. It is a Cloudflare Pages project
named `harness-report` (Pages URL `harness-report-927.pages.dev`; custom domains `harnessreport.com` and
`www.harnessreport.com`). DNS for the domain is the Route 53 zone in the `operator` AWS profile. Edit the
files and redeploy:

```sh
CLOUDFLARE_ACCOUNT_ID=49dbf7b45c8ebadc336657b6c73cbd8a npx -y wrangler pages deploy site --project-name=harness-report --commit-dirty=true
```
