# harness-report

One command. Give it a GitHub repo that contains an AI agent harness and a task; it downloads the repo,
has an AI write a Docker sandbox for it, builds the sandbox, puts a recording proxy between the harness
and the model, and runs the task. Every model call the harness makes is captured on the wire, in one
format, whatever the harness is.

```sh
./run.sh https://github.com/SWE-agent/mini-swe-agent "Create /work/fizzbuzz.py that prints FizzBuzz for 1 to 15 and run it."
./run.sh view runs/swe-agent-mini-swe-agent/<run-id>     # the recorded calls as a conversation
./run.sh <url> "<task>" --rebuild                        # regenerate the recipe and image for this repo
```

Files: `run.sh` (the pipeline), `proxy.py` (the recorder), `.env` (MODEL, AWS_PROFILE, AWS_REGION).

## Stages

| stage | what happens | leaves behind |
|---|---|---|
| fetch | shallow `git clone` | `work/<name>/repo/` |
| analyze | `claude -p` reads the repo and returns a recipe as JSON: a Dockerfile, the env that points the harness at the proxy, the command that runs one task from `$TASK`, and a check command | `work/<name>/recipe.json`, `Dockerfile` |
| build | `docker build` of the recipe, then the check command with no network; a failure is fed back to the AI, three tries | image `hr-<name>` |
| proxy | `proxy.py` in its own container on the `hr-net` network with `~/.aws` mounted read-only; the harness container never holds credentials | |
| run | the sandbox runs the task with the recipe's env; the proxy appends every call to `calls.jsonl` | `runs/<name>/<run-id>/` |

The recipe and image are reused on the next run of the same repo, so the AI and the build run once per repo.

## The proxy

`proxy.py` speaks the OpenAI chat-completions API and the Anthropic messages API on the harness side (tool
calling and streaming on both) and Bedrock on the model side. Whatever model name the harness sends is
recorded and replaced with `MODEL` from `.env`. Each call becomes one JSON line: request, response, tokens,
latency, the model requested, the model used, and any error.

## A run folder

`task.txt`, `command.sh`, `recipe.json`, `calls.jsonl` (the trajectory), `stdout.log`, `stderr.log`,
`proxy.log`, `run.json` (rc, seconds, calls, tokens), plus anything the harness wrote to `/out` itself.

## First run (2026-09-22)

mini-swe-agent at 04d809c on Bedrock Sonnet 4.5, FizzBuzz: analyze 7 turns, $1.59, 122 s; build + check
~70 s; task 21 s, 6 calls through the proxy, 0 errors, harness exit 0. The AI chose litellm's `openai/`
route with `OPENAI_BASE_URL` pointed at the proxy and the model name `gpt-4o`, which the proxy swapped.

## Site

`site/` is harnessreport.com: one self-contained `index.html` (inline CSS, no build, same skeleton as the
ninesweep.com page), `favicon.svg`, `robots.txt`, `sitemap.xml`, `llms.txt`. It is a Cloudflare Pages project
named `harness-report` (Pages URL `harness-report-927.pages.dev`; custom domains `harnessreport.com` and
`www.harnessreport.com`). DNS for the domain is the Route 53 zone in the `operator` AWS profile. Edit the
files and redeploy:

```sh
CLOUDFLARE_ACCOUNT_ID=49dbf7b45c8ebadc336657b6c73cbd8a npx -y wrangler pages deploy site --project-name=harness-report --commit-dirty=true
```
