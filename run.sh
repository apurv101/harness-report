#!/usr/bin/env bash
# run.sh — give it a GitHub repo and a task, or a GitHub repo and a set of Harbor tasks; it downloads the repo,
# has an AI write a sandbox overlay for it, builds it, puts a recording proxy between the harness and the model,
# and runs the task(s). Harbor tasks are verified by their own tests/test.sh and get a reward.
#
#   ./run.sh <github-url> "<task text>"                        one ad-hoc task (no verifier)
#   ./run.sh <github-url> --task-file f                        task text from a file (or pipe it on stdin)
#   ./run.sh <github-url> --taskset aider_polyglot --tasks a,b  Harbor tasks by name
#   ./run.sh <github-url> --taskset aider_polyglot --grep python --limit 20 -k 3
#   ./run.sh tasks aider_polyglot [--grep re]                  list the tasks in a taskset
#   ./run.sh runs [--grep re]                                  list the runs (from each run.json)
#   ./run.sh view runs/<run-id>                                print the recorded model calls as a conversation
#   ./run.sh oracle aider_polyglot a,b                         run each task's solution/solve.sh against its own tests
#   ./run.sh ddb start|stop|reset|status|sync|runs|run <id>     the run store: DynamoDB on the laptop (lib/ddb.sh)
#
#   --taskset S   a Harbor taskset: a directory of task folders, or a name under $HARBOR_TASKS/{datasets,hub-datasets,.}
#   --tasks a,b   task folder names in the taskset      --grep re   regex on task names     --limit N   first N
#   --all         every task in the taskset             -k N        runs per task (default 1)
#   --rebuild     re-clone, re-analyze from scratch (no seed recipe) and rebuild the harness overlay
#   --platform P  image platform for every build and container (default: HR_PLATFORM, else linux/amd64 — what the
#                 AWS runners are; on an arm64 Mac Docker emulates it, slower but the same images)
#   --run-id ID   name the run (default: timestamp)
#   --model M     model for this invocation, e.g. bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0 (default: MODEL in .env)
#   --routes R    per-model routing, pattern=target,... first match wins, MODEL for the rest (default: ROUTES in .env)
#                 targets: bedrock/<id> | anthropic[/<id>] | openai[/<id>]; no /<id> keeps the model the harness asked for
#                 e.g. --routes 'claude-haiku*=anthropic,gpt-4o-mini=openai/gpt-4.1-mini'
#   --egress E    record (default): the sandbox's only way out is the proxy, every connection logged to egress.jsonl
#                 none | allow:a.com,b.org: refuse everything / everything else (the verifier phase is always open)
#                 inspect: record + TLS interception with a per-run CA; bodies in egress/   open: no isolation (old behaviour)
#   --policy P    flag (default): tool calls that touch the tests, git history, the network or rm -rf are flagged in
#                 calls.jsonl and run.json   enforce: flagged actions are rewritten to fail   off
#   --block-url R refuse URLs matching regex R (repeatable; hosts only unless --egress inspect or plain http)
#
# Stages:   fetch     the repo's current HEAD → work/<name>/repo (an existing clone is fetched and reset to it)
#           select    resolve the Harbor tasks; skip multi-container (docker-compose) ones; build the first task image
#           analyze   recipes are kept per commit in recipes/<name>@<sha>.json; the same commit reuses its recipe with
#                     no AI call. A new commit runs claude -p, seeded with the last working recipe for this repo, which
#                     reads the repo and returns a recipe: an OVERLAY Dockerfile (ARG BASE / FROM ${BASE}) that
#                     installs the harness self-contained under /opt/harness, the env that points it at the proxy,
#                     the command that runs one task from $TASK, a check command    → work/<name>/recipe.json
#           build     docker build the overlay FROM the recipe's base image and FROM the first task image; the
#                     check command runs in both; a failure goes back to the AI (3 tries). A recipe that passes is
#                     saved to recipes/, and its diff against the seed goes into each run folder as recipe.diff.
#                     Overlays are labelled with commit, recipe hash and platform, and rebuilt when any differs.
#           proxy     start proxy.py (OpenAI + Anthropic API in, Bedrock out) with ~/.aws; the harness never sees creds
#           run       per task and per k: task image → overlay → agent (instruction.md as $TASK) → tests/test.sh →
#                     reward; every model call lands in runs/<run-id>/calls.jsonl
#
# Every run is one top-level folder, runs/<run-id>/ (<run-id> = timestamp or --run-id, plus -<task>[-k<i>] for a Harbor
# task), holding task.txt command.sh recipe.json calls.jsonl stdout.log stderr.log proxy.log and run.json; a Harbor run
# adds verifier/. run.json says where the run came from (kind prompt|harbor, harness repo+commit, task, model, and
# under provenance: platform, task and overlay image ids, recipe hash, proxy.py version) — written before the run
# starts — and gets rc, seconds, reward, calls and tokens merged in when it ends. `./run.sh runs` lists them.
#
# Layout:   this file is the CLI and the stage spine; each stage is one file in lib/, sourced in the order the
#           pipeline runs them — common.sh (events, errors, timing, image lookups), harbor.sh (tasksets and task
#           images), report.sh (the tasks/runs/view subcommands), fetch.sh, recipe.sh (analyze + build),
#           proxy.sh, execute.sh (one run), ddb.sh (the run store). Everything they print for a person, and
#           everything they write into a run folder, is Python beside them: report.py, recipe.py, runjson.py,
#           task.py, events.py, verifier.py — plus the analyzer's standing prompt (analyze-prompt.md) and the
#           schema it must answer with (recipe-schema.json).
#
# The run store: with HR_DDB=local in .env (./run.sh ddb start), every run, recipe and evaluation is also published
#           to a DynamoDB table as rows — lib/store.py holds the schema, `./run.sh ddb` drives it, and serve.py
#           serves the site from it. Best-effort: the run folder is the record and a run never fails over the table.
#
# .env holds MODEL (a target, e.g. bedrock/<model-id>), AWS_PROFILE, AWS_REGION (needed when any target is Bedrock);
# optional ROUTES, ANTHROPIC_API_KEY / OPENAI_API_KEY (+ ANTHROPIC_BASE_URL / OPENAI_BASE_URL) for the passthrough
# targets, ANALYZER_MODEL (claude -p model) and HARBOR_TASKS (default ~/Desktop/harbor-tasks).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/lib/common.sh"     # emit, die, help, stage, with_timeout, PRELUDE, the image lookups
. "$HERE/lib/harbor.sh"     # tasksets, task.toml, task images, task selection
. "$HERE/lib/report.sh"     # the tasks / runs / view subcommands, and the end-of-sweep table
. "$HERE/lib/ddb.sh"        # the ddb subcommand: the laptop's DynamoDB, and the table every run is published to
. "$HERE/lib/fetch.sh"      # 1. fetch
. "$HERE/lib/recipe.sh"     # 3+4. analyze and build
. "$HERE/lib/proxy.sh"      # 5. proxy
. "$HERE/lib/execute.sh"    # 6. run
. "$HERE/lib/oracle.sh"     # the oracle subcommand: a task's reference solution against its own tests
[ $# -gt 0 ] || { help; exit 0; }
[ -f "$HERE/.env" ] && { set -a; . "$HERE/.env"; set +a; }
HARBOR_TASKS="${HARBOR_TASKS:-$HOME/Desktop/harbor-tasks}"

# ------------------------------------------------------------------ the read-only subcommands
case "${1:-}" in
  tasks) shift; cmd_tasks "$@"; exit 0 ;;
  ddb)   shift; cmd_ddb   "$@"; exit 0 ;;
  oracle) shift; cmd_oracle "$@"; exit $? ;;
  runs)  shift; cmd_runs  "$@" ;;   # both exec python3, so neither returns
  view)  shift; cmd_view  "$@" ;;
esac

# ------------------------------------------------------------------ args
EGRESS="${EGRESS:-record}"; POLICY="${POLICY:-flag}"; BLOCK_URLS="${BLOCK_URLS:-}"
URL=""; TASK=""; TASK_FILE=""; REBUILD=0; RUN_ID=""; TASKSET=""; TASK_NAMES=""; GREP=""; LIMIT=""; ALL=0; K=1
PLATFORM="${HR_PLATFORM:-linux/amd64}"
while [ $# -gt 0 ]; do
  case "$1" in
    --rebuild) REBUILD=1 ;;
    --platform) PLATFORM="${2:?}"; shift ;;
    --run-id) RUN_ID="${2:?}"; shift ;;
    --model) MODEL="${2:?}"; shift ;;
    --routes) ROUTES="${2:?}"; shift ;;
    --egress) EGRESS="${2:?}"; shift ;;
    --policy) POLICY="${2:?}"; shift ;;
    --block-url) BLOCK_URLS="${BLOCK_URLS:+$BLOCK_URLS
}${2:?}"; shift ;;
    --task-file) TASK_FILE="${2:?}"; shift ;;
    --taskset) TASKSET="${2:?}"; shift ;;
    --tasks) TASK_NAMES="${2:?}"; shift ;;
    --grep) GREP="${2:?}"; shift ;;
    --limit) LIMIT="${2:?}"; shift ;;
    --all) ALL=1 ;;
    -k) K="${2:?}"; shift ;;
    -h|--help) help; exit 0 ;;
    --*) die "unknown option $1" ;;
    *) if [ -z "$URL" ]; then URL="$1"; elif [ -z "$TASK" ]; then TASK="$1"; else die "unexpected argument: $1"; fi ;;
  esac; shift
done
[ -n "$URL" ] || die "usage: run.sh <github-url> \"<task>\"   or   run.sh <github-url> --taskset <name> --tasks a,b"
if [ -n "$TASKSET" ]; then
  [ -z "$TASK$TASK_FILE" ] || die "give either a task text or --taskset, not both"
else
  [ -n "$TASK_FILE" ] && TASK="$(cat "$TASK_FILE")"
  [ -n "$TASK" ] || { [ -t 0 ] || TASK="$(cat)"; }
  [ -n "$TASK" ] || die "no task given"
  [ -z "$TASK_NAMES$GREP$LIMIT" ] && [ "$ALL" = 0 ] || die "--tasks/--grep/--limit/--all need --taskset"
fi
[ -f "$HERE/.env" ] || die "no .env (MODEL, AWS_PROFILE, AWS_REGION)"
: "${MODEL:?MODEL in .env or --model}"; ROUTES="${ROUTES:-}"; AWS_REGION="${AWS_REGION:-us-west-2}"
uses_bedrock() { local t; for t in "$MODEL" $(printf '%s' "$ROUTES" | tr ',' '\n' | sed -n 's/^[^=]*=//p'); do
  case "$t" in anthropic|anthropic/*|openai|openai/*) ;; *) return 0 ;; esac; done; return 1; }
case "$EGRESS" in record|none|inspect|open|allow:?*) ;; *) die "--egress: record | none | allow:<hosts> | inspect | open" ;; esac
case "$POLICY" in flag|enforce|off) ;; *) die "--policy: flag | enforce | off" ;; esac
if uses_bedrock; then : "${AWS_PROFILE:?AWS_PROFILE in .env (a route uses Bedrock)}"; fi
docker info >/dev/null 2>&1 || die "Docker is not running"
command -v claude >/dev/null || die "claude CLI not found (the analyze stage runs claude -p)"

[[ "$URL" =~ github\.com[/:]([^/[:space:]]+)/([^/[:space:]#?]+) ]] || die "not a GitHub URL: $URL"
OWNER="${BASH_REMATCH[1]}"; REPO="${BASH_REMATCH[2]%.git}"
NAME="$(printf '%s-%s' "$OWNER" "$REPO" | tr 'A-Z' 'a-z' | tr -c 'a-z0-9.-\n' '-')"
WORK="$HERE/work/$NAME"; SRC="$WORK/repo"; RECIPE="$WORK/recipe.json"; IMAGE="hr-$NAME"; WRAPPER="$WORK/run-harness"
RUN_ID="${RUN_ID:-$(date +%Y%m%dT%H%M%S)}"; mkdir -p "$WORK"
T0=$(date +%s)
echo "repo   https://github.com/$OWNER/$REPO   →   $NAME"
echo "model  $MODEL   (via proxy)"
echo "platform  $PLATFORM$([ "$PLATFORM" != "linux/$(docker version -f '{{.Server.Arch}}' 2>/dev/null)" ] && echo "   (emulated on this machine)")"

# ------------------------------------------------------------------ 1. fetch
stage fetch "current HEAD → work/$NAME/repo"
fetch_repo

# ------------------------------------------------------------------ 2. select (Harbor mode)
TASKS=(); TSD=""; TS_NAME=""; FIRST_TASK_IMG=""; FIRST_TASK_DF=""
if [ -n "$TASKSET" ]; then
  select_tasks
else
  echo "task   $TASK"
  echo "out    runs/$RUN_ID/"
fi

# ------------------------------------------------------------------ 3+4. analyze (AI) and build, with the build error fed back
prepare_recipe

# ------------------------------------------------------------------ 5. proxy image (one per invocation; one container per run)
stage proxy "proxy image hr-proxy, model=$MODEL${ROUTES:+  routes=$ROUTES}  egress=$EGRESS  policy=$POLICY"
build_proxy_image
trap finish_containers EXIT
# a cancel from the site is a SIGTERM to this process group: exit through the EXIT trap so the containers go too
trap 'emit type error msg "cancelled"; exit 143' TERM INT

# ------------------------------------------------------------------ 6. run
RUN_CMD="$(recipe_field run_command)"
if [ -z "$TASKSET" ]; then
  # ---- ad-hoc task: base image from the recipe, no verifier
  OUT="$HERE/runs/$RUN_ID"; mkdir -p "$OUT"; printf '%s\n' "$TASK" > "$OUT/task.txt"
  INSTR="$OUT/task.txt"; OTAG="$IMAGE"; WORKDIR="$(recipe_field workdir /work)"; RUN="$RUN_ID"; TASKNAME=prompt; TDIR=""
  AGENT_T=3600; VERIF_T=0; RES_ARGS=()
  run_one
  echo; echo "done in $(( $(date +%s) - T0 ))s   runs/$RUN_ID/   (run.json task.txt command.sh recipe.json calls.jsonl stdout.log stderr.log proxy.log)"
  echo "view:  ./run.sh view runs/$RUN_ID"
  exit "$RC"
fi

# ---- Harbor tasks: task image → overlay → agent → verifier, k times each
BATCH="$WORK/batch-$RUN_ID.jsonl"; : > "$BATCH"; INFRA_FAIL=0
for TASKNAME in "${TASKS[@]}"; do
  TDIR="$TSD/$TASKNAME"
  IFS=$'\t' read -r _ _ AGENT_T VERIF_T CPUS MEM _ _ < <(task_meta "$TDIR")
  RES_ARGS=(); [ -n "$CPUS" ] && RES_ARGS+=(--cpus "$CPUS"); [ -n "$MEM" ] && RES_ARGS+=(--memory "$MEM")
  stage task "$TASKNAME  (agent ${AGENT_T}s, verifier ${VERIF_T}s${CPUS:+, cpus $CPUS}${MEM:+, mem $MEM})"
  if ! TIMG="$(task_image "$TDIR" "$TS_NAME" "$TASKNAME")"; then echo "task image failed for $TASKNAME; see work/$NAME/task-build.log"; emit type error msg "task image failed for $TASKNAME"; INFRA_FAIL=1; continue; fi
  OTAG="$(overlay_tag "$TASKNAME")"
  # 0, not $FORCE: the labels already tie an image to this commit, recipe and platform; the attempt loop above built and
  # checked the first task's overlay inside $( ), so forcing here would only rebuild it a second time
  if ! ERR="$(build_overlay "$TIMG" "$OTAG" 0 2>&1)"; then echo "$ERR"; echo "overlay failed for $TASKNAME (recorded, skipping)"; emit type error msg "overlay build failed for $TASKNAME"; INFRA_FAIL=1; continue; fi
  echo "$ERR"
  WORKDIR="$(docker image inspect -f '{{.Config.WorkingDir}}' "$TIMG")"; WORKDIR="${WORKDIR:-/app}"
  INSTR="$TDIR/instruction.md"
  for i in $(seq 1 "$K"); do
    RUN="$RUN_ID-$TASKNAME"; [ "$K" -gt 1 ] && RUN="$RUN-k$i"
    OUT="$HERE/runs/$RUN"
    run_one
    printf '{"task":"%s","k":%s,"reward":%s,"rc":%s,"seconds":%s}\n' "$TASKNAME" "$i" "$REWARD" "$RC" "$SECS" >> "$BATCH"
  done
done

stage summary "$NAME × $TS_NAME   $(( $(date +%s) - T0 ))s"
print_summary "$BATCH" "$K"
echo "runs:  runs/$RUN_ID-<task>$([ "$K" -gt 1 ] && echo "-k<i>")/  (run.json task.txt command.sh recipe.json calls.jsonl stdout.log stderr.log proxy.log verifier/)   list: ./run.sh runs --grep $RUN_ID"
echo "view:  ./run.sh view runs/$RUN_ID-<task>$([ "$K" -gt 1 ] && echo "-k<i>")"
exit "$INFRA_FAIL"
