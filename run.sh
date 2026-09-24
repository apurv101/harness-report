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
#
#   --taskset S   a Harbor taskset: a directory of task folders, or a name under $HARBOR_TASKS/{datasets,hub-datasets,.}
#   --tasks a,b   task folder names in the taskset      --grep re   regex on task names     --limit N   first N
#   --all         every task in the taskset             -k N        runs per task (default 1)
#   --rebuild     re-clone, re-analyze and rebuild the harness overlay
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
# Stages:   fetch     git clone → work/<name>/repo
#           select    resolve the Harbor tasks; skip multi-container (docker-compose) ones; build the first task image
#           analyze   claude -p reads the repo and returns a recipe: an OVERLAY Dockerfile (ARG BASE / FROM ${BASE})
#                     that installs the harness self-contained under /opt/harness, the env that points it at the
#                     proxy, the command that runs one task from $TASK, a check command    → work/<name>/recipe.json
#           build     docker build the overlay FROM the recipe's base image and FROM the first task image; the
#                     check command runs in both; a failure goes back to the AI (3 tries)
#           proxy     start proxy.py (OpenAI + Anthropic API in, Bedrock out) with ~/.aws; the harness never sees creds
#           run       per task and per k: task image → overlay → agent (instruction.md as $TASK) → tests/test.sh →
#                     reward; every model call lands in runs/<run-id>/calls.jsonl
#
# Every run is one top-level folder, runs/<run-id>/ (<run-id> = timestamp or --run-id, plus -<task>[-k<i>] for a Harbor
# task), holding task.txt command.sh recipe.json calls.jsonl stdout.log stderr.log proxy.log and run.json; a Harbor run
# adds verifier/. run.json says where the run came from (kind prompt|harbor, harness repo+commit, task, model) — written
# before the run starts — and gets rc, seconds, reward, calls and tokens merged in when it ends. `./run.sh runs` lists them.
#
# .env holds MODEL (a target, e.g. bedrock/<model-id>), AWS_PROFILE, AWS_REGION (needed when any target is Bedrock);
# optional ROUTES, ANTHROPIC_API_KEY / OPENAI_API_KEY (+ ANTHROPIC_BASE_URL / OPENAI_BASE_URL) for the passthrough
# targets, ANALYZER_MODEL (claude -p model) and HARBOR_TASKS (default ~/Desktop/harbor-tasks).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
die() { echo "run.sh: $*" >&2; exit 2; }
help() { awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "$0"; }
[ $# -gt 0 ] || { help; exit 0; }
[ -f "$HERE/.env" ] && { set -a; . "$HERE/.env"; set +a; }
HARBOR_TASKS="${HARBOR_TASKS:-$HOME/Desktop/harbor-tasks}"

# ------------------------------------------------------------------ Harbor task helpers
# taskset_dir <name-or-path>: the directory holding the task folders.
taskset_dir() {
  local d; for d in "$1" "$HARBOR_TASKS/datasets/$1" "$HARBOR_TASKS/hub-datasets/$1" "$HARBOR_TASKS/$1"; do
    [ -d "$d" ] && { cd "$d" && pwd; return; }; done
  die "no taskset '$1' (looked in $HARBOR_TASKS/{datasets,hub-datasets,.})"
}
# task_meta <task-dir>: one tab-separated line: difficulty category agent_timeout verifier_timeout cpus memory docker_image compose
task_meta() { python3 - "$1" <<'PY'
import sys, tomllib, os
d = sys.argv[1]; t = tomllib.load(open(f"{d}/task.toml", "rb"))
env = t.get("environment", {}); m = t.get("metadata", {})
mem = env.get("memory_mb"); mem = f"{int(mem)}m" if mem else str(env.get("memory", "")).lower()
compose = "compose" if any(os.path.exists(f"{d}/environment/{f}") for f in ("docker-compose.yaml", "docker-compose.yml", "compose.yaml")) else ""
print("\t".join(str(x) for x in [m.get("difficulty", ""), m.get("category", ""), int(t.get("agent", {}).get("timeout_sec", 1800)),
      int(t.get("verifier", {}).get("timeout_sec", 1800)), env.get("cpus", ""), mem, env.get("docker_image", ""), compose]))
PY
}
# list_tasks <taskset-dir> [regex]: task folder names (those with a task.toml), sorted.
list_tasks() { local d; for d in "$1"/*/; do [ -f "$d/task.toml" ] && basename "$d"; done | { [ -n "${2:-}" ] && grep -E -- "$2" || cat; } | sort; }

# ------------------------------------------------------------------ tasks
if [ "${1:-}" = tasks ]; then
  TS="${2:?usage: run.sh tasks <taskset> [--grep re]}"; RE=""; [ "${3:-}" = --grep ] && RE="${4:?}"
  TSD="$(taskset_dir "$TS")"; N=0
  while IFS= read -r t; do
    IFS=$'\t' read -r diff cat _ _ _ _ _ compose < <(task_meta "$TSD/$t")
    printf '%-60s %-8s %-24s %s\n' "$t" "$diff" "$cat" "${compose:+(multi-container, skipped)}"; N=$((N+1))
  done < <(list_tasks "$TSD" "$RE")
  echo "$N tasks in $TSD"; exit 0
fi

# ------------------------------------------------------------------ runs
if [ "${1:-}" = runs ]; then
  RE=""; [ "${2:-}" = --grep ] && RE="${3:?}"
  exec python3 - "$HERE/runs" "$RE" <<'PY'
import json, os, re, sys
root, pat = sys.argv[1:]
rows = []
for d in sorted(os.listdir(root) if os.path.isdir(root) else [], reverse=True):
    p = os.path.join(root, d, "run.json")
    if not os.path.isfile(p) or (pat and not re.search(pat, d)): continue
    r = json.load(open(p)); t = r.get("task") or {}
    rows.append((d, r.get("kind", "?"), (r.get("harness") or {}).get("name", "?"), t.get("name") or (r.get("prompt") or "")[:40].replace("\n", " "),
                 (r.get("model") or "").split("/")[-1][:28], "-" if r.get("rc") is None else r["rc"], "-" if r.get("reward") is None else r["reward"],
                 "-" if r.get("seconds") is None else f"{r['seconds']}s", "-" if r.get("calls") is None else r["calls"], "" if r.get("finished") else "(unfinished)"))
if not rows: sys.exit("no runs" + (f" matching {pat!r}" if pat else "") + f" in {root}")
hdr = ["run", "kind", "harness", "task", "model", "rc", "reward", "time", "calls", ""]
w = [max([len(hdr[i])] + [len(str(x[i])) for x in rows]) for i in range(len(hdr))]
print("  ".join(h.ljust(w[i]) for i, h in enumerate(hdr)).rstrip())
for x in rows: print("  ".join(str(v).ljust(w[i]) for i, v in enumerate(x)).rstrip())
PY
fi

# ------------------------------------------------------------------ view
if [ "${1:-}" = view ]; then
  D="${2:?usage: run.sh view runs/<run-id>}"; [ -f "$D/calls.jsonl" ] || D="$(dirname "$D")"
  exec python3 - "$D/calls.jsonl" <<'PY'
import json, sys
calls = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
if not calls: sys.exit("no calls recorded")
tin = sum(c["usage"].get("input_tokens") or 0 for c in calls); tout = sum(c["usage"].get("output_tokens") or 0 for c in calls)
errs = sum(1 for c in calls if c.get("error"))
print(f"{len(calls)} model calls   route={calls[0]['route']}   model={calls[0]['model']}   tokens in={tin} out={tout}   errors={errs}")
print("-" * 78)
last = calls[-1]; req = last["request"]; route = last["route"]
def text(c):
    if isinstance(c, str): return c
    return "\n".join(p.get("text", json.dumps(p)) if isinstance(p, dict) and p.get("type") in ("text", None) else json.dumps(p) for p in (c or []))
def clip(s, n=500): s = s.strip(); return s if len(s) <= n else s[:n] + f" … [{len(s)-n} more]"
if route == "openai":
    sysm = [m for m in req["messages"] if m["role"] in ("system", "developer")]
    for m in sysm: print("SYSTEM\n    " + clip(text(m["content"]), 300).replace("\n", "\n    ") + "\n")
    for m in req["messages"]:
        r = m["role"]
        if r in ("system", "developer"): continue
        if r == "assistant":
            t = text(m.get("content")); print("ASSISTANT");
            if t.strip(): print("    " + clip(t).replace("\n", "\n    "))
            for tc in m.get("tool_calls") or []:
                a = tc["function"]["arguments"]
                try: a = json.loads(a); a = a.get("command") or a.get("cmd") or a.get("code") or json.dumps(a)
                except Exception: pass
                print("    $ " + str(a).replace("\n", "\n      "))
        elif r == "tool": print("OBSERVATION\n    " + clip(text(m.get("content"))).replace("\n", "\n    "))
        else: print("USER\n    " + clip(text(m.get("content"))).replace("\n", "\n    "))
        print()
    rm = last["response"]["choices"][0]["message"] if last.get("response") else {}
    print("ASSISTANT (final)"); print("    " + clip(text(rm.get("content") or "")).replace("\n", "\n    "))
    for tc in rm.get("tool_calls") or []: print("    $ " + tc["function"]["arguments"])
else:
    if req.get("system"): print("SYSTEM\n    " + clip(text(req["system"]), 300).replace("\n", "\n    ") + "\n")
    for m in req["messages"]:
        print(m["role"].upper())
        for b in (m["content"] if isinstance(m["content"], list) else [{"type": "text", "text": m["content"]}]):
            t = b.get("type")
            if t == "text": print("    " + clip(b["text"]).replace("\n", "\n    "))
            elif t == "tool_use": print("    $ " + json.dumps(b.get("input")))
            elif t == "tool_result": print("    → " + clip(text(b.get("content"))).replace("\n", "\n    "))
        print()
    print("ASSISTANT (final)")
    for b in (last.get("response") or {}).get("content", []):
        if b.get("type") == "text": print("    " + clip(b["text"]).replace("\n", "\n    "))
        elif b.get("type") == "tool_use": print("    $ " + json.dumps(b.get("input")))
PY
fi

# ------------------------------------------------------------------ args
EGRESS="${EGRESS:-record}"; POLICY="${POLICY:-flag}"; BLOCK_URLS="${BLOCK_URLS:-}"
URL=""; TASK=""; TASK_FILE=""; REBUILD=0; RUN_ID=""; TASKSET=""; TASK_NAMES=""; GREP=""; LIMIT=""; ALL=0; K=1
while [ $# -gt 0 ]; do
  case "$1" in
    --rebuild) REBUILD=1 ;;
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
T0=$(date +%s); stage() { echo; echo "━━ [$1] $(( $(date +%s) - T0 ))s  ${2:-}"; }
# portable timeout: coreutils timeout / gtimeout if present, else perl alarm (exit 142 on expiry)
with_timeout() { local s="$1"; shift
  if command -v timeout >/dev/null 2>&1; then timeout "$s" "$@"
  elif command -v gtimeout >/dev/null 2>&1; then gtimeout "$s" "$@"
  else perl -e 'alarm shift; exec @ARGV' "$s" "$@"; fi; }
# Every command in a sandbox runs through `bash -lc` (so the image's profile.d scripts apply). Debian's /etc/profile
# resets PATH, which would hide the overlay's /opt/harness/bin; HR_PATH carries the image's PATH and PRELUDE restores it.
PRELUDE='[ -n "${HR_PATH:-}" ] && export PATH="$HR_PATH"; '
image_path() { docker image inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$1" | sed -n 's/^PATH=//p' | head -1; }
echo "repo   https://github.com/$OWNER/$REPO   →   $NAME"
echo "model  $MODEL   (via proxy)"

# ------------------------------------------------------------------ 1. fetch
stage fetch "git clone → work/$NAME/repo"
if [ -d "$SRC/.git" ] && [ "$REBUILD" = 0 ]; then echo "already cloned ($(git -C "$SRC" rev-parse --short HEAD)); --rebuild to re-clone"
else rm -rf "$SRC"; git clone -q --depth 1 "https://github.com/$OWNER/$REPO" "$SRC"; echo "cloned $(git -C "$SRC" rev-parse --short HEAD)"; fi
COMMIT="$(git -C "$SRC" rev-parse HEAD)"
printf '{"repo":"https://github.com/%s/%s","commit":"%s"}\n' "$OWNER" "$REPO" "$COMMIT" > "$WORK/source.json"

# ------------------------------------------------------------------ 2. select (Harbor mode)
# task_image <task-dir> <taskset> <task>: builds environment/Dockerfile (or pulls task.toml's docker_image); echoes the tag
task_image() {
  local tdir="$1" tag="hr-task/$2:$3" prebuilt
  if [ -f "$tdir/environment/Dockerfile" ]; then
    docker build -q -t "$tag" "$tdir/environment" > "$WORK/task-build.log" 2>&1 || { tail -30 "$WORK/task-build.log" >&2; return 1; }
  else
    IFS=$'\t' read -r _ _ _ _ _ _ prebuilt _ < <(task_meta "$tdir")
    [ -n "$prebuilt" ] || { echo "task $3 has neither environment/Dockerfile nor docker_image" >&2; return 1; }
    docker image inspect "$prebuilt" >/dev/null 2>&1 || docker pull -q "$prebuilt" >/dev/null || return 1
    tag="$prebuilt"
  fi
  echo "$tag"
}
TASKS=(); TSD=""; TS_NAME=""; FIRST_TASK_IMG=""; FIRST_TASK_DF=""
if [ -n "$TASKSET" ]; then
  TSD="$(taskset_dir "$TASKSET")"; TS_NAME="$(basename "$TSD" | tr 'A-Z' 'a-z' | tr -c 'a-z0-9_.-\n' '-')"
  stage select "taskset $TS_NAME ($TSD)"
  if [ -n "$TASK_NAMES" ]; then
    IFS=, read -r -a WANT <<< "$TASK_NAMES"
    for t in "${WANT[@]}"; do [ -f "$TSD/$t/task.toml" ] || die "no task '$t' in $TSD"; done
    CAND=("${WANT[@]}")
  else
    [ -n "$GREP$LIMIT" ] || [ "$ALL" = 1 ] || die "taskset has $(list_tasks "$TSD" | wc -l | tr -d ' ') tasks; pick with --tasks, --grep, --limit or --all"
    CAND=(); while IFS= read -r t; do CAND+=("$t"); done < <(list_tasks "$TSD" "$GREP" | { [ -n "$LIMIT" ] && head -n "$LIMIT" || cat; })
  fi
  for t in "${CAND[@]}"; do
    IFS=$'\t' read -r _ _ _ _ _ _ _ compose < <(task_meta "$TSD/$t")
    if [ -n "$compose" ]; then echo "skip   $t  (multi-container task; not supported by this runner)"; else TASKS+=("$t"); fi
  done
  [ "${#TASKS[@]}" -gt 0 ] || die "no runnable tasks selected"
  echo "tasks  ${#TASKS[@]} × k=$K:  ${TASKS[*]:0:8}$([ "${#TASKS[@]}" -gt 8 ] && echo " …")"
  echo "task image  $TS_NAME:${TASKS[0]}  (the overlay is validated against it)"
  FIRST_TASK_IMG="$(task_image "$TSD/${TASKS[0]}" "$TS_NAME" "${TASKS[0]}")" || die "could not build the task image for ${TASKS[0]}; see work/$NAME/task-build.log"
  [ -f "$TSD/${TASKS[0]}/environment/Dockerfile" ] && FIRST_TASK_DF="$(grep -v '^\s*#' "$TSD/${TASKS[0]}/environment/Dockerfile" | grep -v '^\s*$' | head -40)"
  echo "out    runs/$RUN_ID-<task>$([ "$K" -gt 1 ] && echo "-k<i>")/"
else
  echo "task   $TASK"
  echo "out    runs/$RUN_ID/"
fi

# ------------------------------------------------------------------ 3+4. analyze (AI) and build, with the build error fed back
SCHEMA='{"type":"object","required":["summary","base_image","dockerfile","run_command","check_command","env","api_style"],"properties":{
 "summary":{"type":"string","description":"one paragraph: what the harness is, its entrypoint, how it calls the model"},
 "base_image":{"type":"string","description":"official image the overlay is built FROM when no task image is given (also the ARG BASE default), e.g. python:3.12-slim-bookworm"},
 "dockerfile":{"type":"string","description":"complete OVERLAY Dockerfile: first line ARG BASE=<base_image>, second line FROM ${BASE}; build context is the repo root"},
 "run_command":{"type":"string","description":"bash, run inside the container with cwd = the task working directory, runs ONE task from $TASK non-interactively and exits"},
 "check_command":{"type":"string","description":"bash, verifies the install without calling a model (e.g. the CLI --help)"},
 "env":{"type":"array","items":{"type":"object","required":["name","value"],"properties":{"name":{"type":"string"},"value":{"type":"string"}}},
        "description":"environment for the run: routes the harness model calls to $PROXY_URL (literal placeholder), picks the model name, disables wizards/prompts"},
 "api_style":{"type":"string","enum":["openai","anthropic"],"description":"which API the harness will speak to the proxy"},
 "workdir":{"type":"string","description":"working directory for an ad-hoc task (default /work); Harbor tasks use their own image WORKDIR"},
 "notes":{"type":"string"}}}'

analyze() {  # $1 = feedback from a failed build/check, or empty
  local tree; tree="$(cd "$SRC" && find . -maxdepth 2 -not -path './.git*' -not -path './node_modules*' | sort | head -150)"
  local prompt
  prompt="You are packaging the AI agent harness in the current directory (a fresh clone of https://github.com/$OWNER/$REPO) so it can run ONE task inside a Docker sandbox, with all its model calls going through a recording proxy. Read the repo (README, manifests, the CLI entrypoint, the model/provider client code) and return the recipe as JSON matching the schema.

THE PROXY CONTRACT
- The proxy is reachable from the container at \$PROXY_URL (literal string; it is substituted at run time). It speaks BOTH
  the OpenAI chat-completions API (\$PROXY_URL/v1/chat/completions, list at \$PROXY_URL/v1/models) and the Anthropic
  messages API (\$PROXY_URL/v1/messages). Streaming and tool calling work on both. Any API key string is accepted.
- The proxy routes each call by the model name the harness sends: it may serve that exact model or swap it for another.
  So keep the harness's own default model name(s) where it has them (a harness that uses several models for different
  roles must keep sending distinct names); only if it has none, pick a real model name it accepts (e.g. for litellm use
  an 'openai/<name>' or 'anthropic/<name>' prefix so the base URL applies; for the Anthropic SDK a claude name).
- The harness must NOT need any cloud credentials or network access other than the proxy at run time.
  Typical env: OPENAI_BASE_URL=\$PROXY_URL/v1 + OPENAI_API_KEY=proxy, or ANTHROPIC_BASE_URL=\$PROXY_URL + ANTHROPIC_API_KEY=proxy,
  plus whatever variable this harness uses to choose the model, plus anything that skips first-run wizards, telemetry,
  confirmations, or interactive prompts (stdin is NOT a tty).

THE OVERLAY DOCKERFILE
- The Dockerfile is an OVERLAY: its first two instructions MUST be 'ARG BASE=<base_image>' and 'FROM \${BASE}'. We build it
  on top of images chosen at build time: your base_image for ad-hoc tasks, and benchmark task images (Debian/Ubuntu
  userland with apt-get, e.g. buildpack-deps:jammy or python:3.x-slim, which carry their own python/node/toolchains that
  the task's tests depend on). So: assume only a Debian/Ubuntu base with apt-get; NEVER rely on or change the base
  image's python/node/packages. Install the harness runtime SELF-CONTAINED under /opt/harness (python: install uv into
  /opt/harness, 'uv python install <ver>' with UV_PYTHON_INSTALL_DIR under /opt/harness, then install the harness with
  uv into a venv or tool dir there; node: unpack an official node tarball into /opt/harness/node) and put its bin
  directories on PATH with ENV PATH=/opt/harness/bin:...:\$PATH. apt-get only what is missing (ca-certificates, curl, git...).
- Build context is the repo root: COPY the source in (e.g. to /opt/harness/src) and install it from there so the
  entrypoint is the harness's own CLI. Do not bake in secrets. Do not run the harness during the build. The harness is
  never modified. Do not set WORKDIR to the harness source; the run happens in the task's directory.

THE RUN COMMAND
- bash, run inside the container via 'bash -lc' with the env above, cwd = the task's working directory (the harness must
  read and edit files THERE), and the task text in \$TASK. It must run exactly one task non-interactively through the
  harness's own CLI entrypoint and exit when done. If the harness can write its own trajectory/log/history to a path,
  write it under /out/ (mounted from the host). Use \$TASK unquoted-safe: e.g. -t \"\$TASK\". No 'cd' into the harness source.
- check_command: something fast that proves the install works without calling a model (e.g. the CLI --help).

Repository tree (2 levels):
$tree"
  [ -n "$FIRST_TASK_DF" ] && prompt="$prompt

The overlay will also be built FROM this benchmark task image (its Dockerfile, comments stripped); the check command must pass there too:
$FIRST_TASK_DF"
  [ -n "$1" ] && prompt="$prompt

THE PREVIOUS RECIPE FAILED. Fix it. Previous recipe:
$(cat "$RECIPE" 2>/dev/null)

Error output:
$1"
  local raw
  raw="$(cd "$SRC" && claude -p "$prompt" --output-format json --json-schema "$SCHEMA" \
          --allowedTools "Read,Glob,Grep" --max-turns 60 --strict-mcp-config ${ANALYZER_MODEL:+--model "$ANALYZER_MODEL"} 2>"$WORK/analyze.stderr" || true)"
  printf '%s' "$raw" > "$WORK/analyze.raw.json"
  python3 - "$WORK/analyze.raw.json" "$RECIPE" "$WORK/Dockerfile" <<'PY' || return 1
import json, sys, re
raw, recipe, dockerfile = sys.argv[1:]
d = json.load(open(raw))
so = d.get("structured_output")
if not so: sys.exit(f"analyze: no structured output (subtype={d.get('subtype')}, result={str(d.get('result'))[:300]})")
lines = [l.strip() for l in so["dockerfile"].splitlines() if l.strip() and not l.strip().startswith("#")]
if not (len(lines) > 1 and re.match(r"ARG\s+BASE(=|\s|$)", lines[0]) and re.match(r"FROM\s+(--platform=\S+\s+)?\$\{?BASE\}?(\s|$)", lines[1])):
    sys.exit("recipe rejected: the dockerfile must begin with 'ARG BASE=<base_image>' then 'FROM ${BASE}' (it is an overlay built on top of an image chosen at build time). It began with:\n" + "\n".join(lines[:3]))
json.dump(so, open(recipe, "w"), indent=2)
open(dockerfile, "w").write(so["dockerfile"].rstrip() + "\n")
print(f"recipe: api={so['api_style']}  base={so['base_image']}  env={' '.join(e['name'] for e in so['env'])}  cost=${d.get('total_cost_usd', 0):.2f}  turns={d.get('num_turns')}")
print("summary: " + so["summary"].strip().replace("\n", " ")[:600])
print("run_command: " + so["run_command"].strip())
PY
}
recipe_field() { python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); print(r[sys.argv[2]] if len(sys.argv)<4 else (r.get(sys.argv[2]) or sys.argv[3]))' "$RECIPE" "$@"; }
# recipe_ok: the saved recipe has every field this version needs and its Dockerfile is an overlay (older recipes are re-analyzed)
recipe_ok() { python3 -c 'import json,sys,re; r=json.load(open(sys.argv[1])); ls=[l.strip() for l in r.get("dockerfile","").splitlines() if l.strip() and not l.strip().startswith("#")]
sys.exit(0 if all(k in r for k in ("base_image","dockerfile","run_command","check_command","env","api_style")) and len(ls)>1 and re.match(r"ARG\s+BASE",ls[0]) and "BASE" in ls[1] else 1)' "$RECIPE" 2>/dev/null; }
# write_wrapper: the script every run execs inside the sandbox — run-harness <workdir> <instruction-file>
write_wrapper() {
  { printf '#!/bin/bash\n# generated by run.sh from recipe.json: run-harness <workdir> <instruction-file>\n'
    printf '[ -n "${HR_PATH:-}" ] && export PATH="$HR_PATH"\nmkdir -p "$1" /out /logs/agent 2>/dev/null; cd "$1"\nTASK="$(cat "$2")"; export TASK\n'
    recipe_field run_command; } > "$WRAPPER"; chmod +x "$WRAPPER"
}
check_image() {  # $1 = image: run the recipe's check command inside it, no network
  local chk; chk="$(recipe_field check_command)"
  docker run --rm --network none -e "HR_PATH=$(image_path "$1")" "$1" bash -lc "$PRELUDE$chk" > "$WORK/check.log" 2>&1 \
    || { echo "check command failed in $1: $chk"; tail -40 "$WORK/check.log"; return 1; }
}
BUILT=" "
build_overlay() {  # $1 = base image, $2 = tag, $3 = force(0/1): docker build the overlay FROM $1, then the check
  case "$BUILT" in *" $2 "*) return 0;; esac
  if [ "$3" = 0 ] && docker image inspect "$2" >/dev/null 2>&1; then echo "overlay $2 exists"; BUILT="$BUILT$2 "; return 0; fi
  docker build -q --build-arg BASE="$1" -t "$2" -f "$WORK/Dockerfile" "$SRC" > "$WORK/build.log" 2>&1 \
    || { echo "docker build FROM $1 failed:"; tail -40 "$WORK/build.log"; return 1; }
  echo "overlay $2 built FROM $1"
  check_image "$2" || return 1
  echo "check passed in $2"; BUILT="$BUILT$2 "
}
overlay_tag() { echo "$IMAGE/$TS_NAME:$1"; }

NEED_ANALYZE=0; FORCE=0; [ "$REBUILD" = 1 ] && NEED_ANALYZE=1
if [ ! -f "$RECIPE" ]; then NEED_ANALYZE=1; elif ! recipe_ok; then echo "recipe work/$NAME/recipe.json is from an older schema (not an overlay); re-analyzing"; NEED_ANALYZE=1; fi
FEEDBACK=""; OK=0
for attempt in 1 2 3; do
  if [ "$NEED_ANALYZE" = 1 ]; then
    stage analyze "attempt $attempt: claude -p reads the repo and writes the recipe (work/$NAME/{recipe.json,Dockerfile})"
    if A="$(analyze "$FEEDBACK" 2>&1)"; then echo "$A"; else echo "$A"; FEEDBACK="$A"; continue; fi
    FORCE=1
  else
    stage analyze "recipe exists: work/$NAME/recipe.json (--rebuild to regenerate)"
    echo "api=$(recipe_field api_style)  base=$(recipe_field base_image)  run_command: $(recipe_field run_command)"
  fi
  write_wrapper
  stage build "overlay FROM $(recipe_field base_image)${FIRST_TASK_IMG:+ and FROM $FIRST_TASK_IMG}"
  if ERR="$( { build_overlay "$(recipe_field base_image)" "$IMAGE" "$FORCE" && { [ -z "$FIRST_TASK_IMG" ] || build_overlay "$FIRST_TASK_IMG" "$(overlay_tag "${TASKS[0]}")" "$FORCE"; }; } 2>&1 )"; then
    echo "$ERR"; OK=1; break
  else echo "$ERR"; FEEDBACK="$ERR"; NEED_ANALYZE=1; fi
done
[ "$OK" = 1 ] || die "could not build a working sandbox after 3 attempts; see work/$NAME/{build.log,check.log,analyze.stderr}"

# ------------------------------------------------------------------ 5. proxy image (one per invocation; one container per run)
stage proxy "proxy image hr-proxy, model=$MODEL${ROUTES:+  routes=$ROUTES}  egress=$EGRESS  policy=$POLICY"
docker network inspect hr-net >/dev/null 2>&1 || docker network create hr-net >/dev/null
# hr-int has no route out: a harness container on it reaches the world only through the proxy, which sits on both
docker network inspect hr-int >/dev/null 2>&1 || docker network create --internal hr-int >/dev/null
CONTROL_TOKEN="$(python3 -c 'import secrets; print(secrets.token_hex(16))')"   # lets run.sh (not the harness) open the verify phase
PCTX="$WORK/.proxy-ctx"; mkdir -p "$PCTX"; cp "$HERE/proxy.py" "$HERE/policy.py" "$PCTX/"
printf 'FROM python:3.12-slim\nRUN pip install -q --root-user-action=ignore boto3 cryptography\nCOPY proxy.py policy.py /\nCMD ["python3","-u","/proxy.py"]\n' > "$PCTX/Dockerfile"
docker build -q -t hr-proxy "$PCTX" >/dev/null
CUR_PROXY=""; CUR_RUN=""; CUR_OUT=""
finish_containers() {
  [ -n "$CUR_RUN" ] && { docker rm -f "$CUR_RUN" >/dev/null 2>&1 || true; }
  [ -n "$CUR_PROXY" ] && { docker logs "$CUR_PROXY" > "$CUR_OUT/proxy.log" 2>&1 || true; docker rm -f "$CUR_PROXY" >/dev/null 2>&1 || true; }
  CUR_RUN=""; CUR_PROXY=""
}
trap finish_containers EXIT
start_proxy() {  # $1 = container name, $2 = out dir → sets PROXY_URL
  CUR_PROXY="$1"; CUR_OUT="$2"
  docker rm -f "$1" >/dev/null 2>&1 || true
  # keys are passed by name (-e VAR), so their values never appear in the docker command line
  local PENV=() v; for v in AWS_PROFILE ANTHROPIC_API_KEY ANTHROPIC_BASE_URL OPENAI_API_KEY OPENAI_BASE_URL; do
    [ -n "${!v:-}" ] && { export "${v?}"; PENV+=(-e "$v"); }; done
  # Harbor: the task's tests (and environment, to discount lines it already holds) go to the PROXY only, for the
  # verifier_leak check; the harness container never gets them before the verify stage
  local TMOUNT=(); if [ -n "${TDIR:-}" ] && [ -d "$TDIR/tests" ]; then TMOUNT+=(-v "$TDIR/tests:/hr/tests:ro" -e TESTS_DIR=/hr/tests)
    [ -d "$TDIR/environment" ] && TMOUNT+=(-v "$TDIR/environment:/hr/env:ro" -e ENV_DIR=/hr/env); fi
  docker run -d --name "$1" --network hr-net -v "$HOME/.aws:/root/.aws:ro" -v "$2:/out" \
    -e "MODEL=$MODEL" -e "ROUTES=$ROUTES" -e "AWS_REGION=$AWS_REGION" -e "AWS_DEFAULT_REGION=$AWS_REGION" -e LOG=/out/calls.jsonl \
    -e "EGRESS=$EGRESS" -e "POLICY=$POLICY" -e "BLOCK_URLS=$BLOCK_URLS" -e "CONTROL_TOKEN=$CONTROL_TOKEN" -e "SELF_HOSTS=$1" \
    ${PENV[@]+"${PENV[@]}"} ${TMOUNT[@]+"${TMOUNT[@]}"} hr-proxy >/dev/null
  [ "$EGRESS" = open ] || docker network connect hr-int "$1"
  local i; for i in $(seq 1 30); do
    docker exec "$1" python3 -c "import urllib.request;urllib.request.urlopen('http://localhost:4000/health',timeout=2)" 2>/dev/null && break
    sleep 1; [ "$i" = 30 ] && { docker logs "$1"; die "proxy did not come up"; }
  done
  PROXY_URL="http://$1:4000"
  # what the harness container gets: its network, and the env that sends every client through the egress proxy
  HNET=hr-net; HENV=()
  if [ "$EGRESS" != open ]; then
    HNET=hr-int; local v; for v in HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy; do HENV+=(-e "$v=http://$1:3128"); done
    HENV+=(-e "NO_PROXY=$1,localhost,127.0.0.1" -e "no_proxy=$1,localhost,127.0.0.1" -e NODE_USE_ENV_PROXY=1)
    if [ "$EGRESS" = inspect ]; then for v in SSL_CERT_FILE REQUESTS_CA_BUNDLE NODE_EXTRA_CA_CERTS CURL_CA_BUNDLE GIT_SSL_CAINFO; do HENV+=(-e "$v=/out/hr-ca.pem"); done; fi
  fi
}
proxy_phase() {  # $1 = agent | verify
  [ "$EGRESS" = open ] || docker exec -e "T=$CONTROL_TOKEN" -e "P=$1" "$CUR_PROXY" python3 -c "import os,urllib.request
urllib.request.urlopen(urllib.request.Request('http://localhost:4000/_hr/phase', data=('{\"phase\":\"'+os.environ['P']+'\"}').encode(), headers={'X-HR-Token': os.environ['T']}), timeout=5)" >/dev/null
}

# ------------------------------------------------------------------ 6. run
RUN_CMD="$(recipe_field run_command)"
# run_one: uses OUT INSTR OTAG WORKDIR RUN TASKNAME TDIR AGENT_T VERIF_T RES_ARGS; sets RC REWARD SECS
run_one() {
  mkdir -p "$OUT"; [ -z "$TDIR" ] || mkdir -p "$OUT/verifier"; cp "$RECIPE" "$OUT/recipe.json"; [ "$INSTR" -ef "$OUT/task.txt" ] || cp "$INSTR" "$OUT/task.txt"
  printf '%s\n' "$RUN_CMD" > "$OUT/command.sh"
  # run.json, origin half: written before anything runs, so even a run that dies says where it came from
  python3 - "$OUT" "$RUN" "$NAME" "$OWNER/$REPO" "$COMMIT" "$TS_NAME" "$TSD" "$TASKNAME" "$MODEL" "$WORKDIR" "$RUN_CMD" "$(recipe_field api_style)" "$ROUTES" "$EGRESS" "$POLICY" "$BLOCK_URLS" <<'PY'
import json, sys, time
out, run, name, repo, commit, taskset, tsd, task, model, workdir, cmd, api, routes, egress, pol, blocks = sys.argv[1:]
rec = {"run": run, "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "finished": None, "kind": "harbor" if taskset else "prompt",
       "harness": {"name": name, "repo": "https://github.com/" + repo, "commit": commit, "api_style": api},
       "task": {"name": task, "taskset": taskset, "taskset_dir": tsd} if taskset else {"name": None, "taskset": None},
       "prompt": None if taskset else open(f"{out}/task.txt").read().strip(),
       "model": model, "routes": routes or None,
       "interception": {"egress": egress, "policy": pol, "block_urls": [b for b in blocks.split("\n") if b]}, "workdir": workdir, "run_command": cmd}
json.dump(rec, open(f"{out}/run.json", "w"), indent=2)
PY
  stage proxy "recording → ${OUT#$HERE/}/calls.jsonl"
  start_proxy "hr-proxy-$RUN" "$OUT"
  local ENV_ARGS=(); while IFS= read -r kv; do ENV_ARGS+=(-e "$kv"); done < <(
    PROXY_URL="$PROXY_URL" python3 -c 'import json,os,sys
for e in json.load(open(sys.argv[1]))["env"]: print(e["name"]+"="+e["value"].replace("$PROXY_URL", os.environ["PROXY_URL"]).replace("${PROXY_URL}", os.environ["PROXY_URL"]))' "$RECIPE")
  stage run "$TASKNAME  cwd=$WORKDIR  timeout=${AGENT_T}s  $RUN_CMD"
  CUR_RUN="hr-run-$RUN"; docker rm -f "$CUR_RUN" >/dev/null 2>&1 || true
  local LOGS_MOUNT=(); [ -z "$TDIR" ] || LOGS_MOUNT=(-v "$OUT:/logs")   # Harbor: /logs/agent, /logs/verifier/reward.txt
  docker run -d --name "$CUR_RUN" --network "$HNET" -w "$WORKDIR" ${RES_ARGS[@]+"${RES_ARGS[@]}"} \
    -v "$OUT:/out" ${LOGS_MOUNT[@]+"${LOGS_MOUNT[@]}"} -v "$INSTR:/task/instruction.md:ro" -v "$WRAPPER:/usr/local/bin/run-harness:ro" \
    -e "PROXY_URL=$PROXY_URL" -e "HR_PATH=$(image_path "$OTAG")" -e TEST_DIR=/tests ${HENV[@]+"${HENV[@]}"} ${ENV_ARGS[@]+"${ENV_ARGS[@]}"} "$OTAG" sleep infinity >/dev/null
  local START; START=$(date +%s); set +e
  with_timeout "$AGENT_T" docker exec -w "$WORKDIR" "$CUR_RUN" bash -lc "${PRELUDE}run-harness $WORKDIR /task/instruction.md" 2>"$OUT/stderr.log" | tee "$OUT/stdout.log"
  RC=${PIPESTATUS[0]}; set -e
  SECS=$(( $(date +%s) - START ))
  { [ "$RC" = 124 ] || [ "$RC" = 142 ]; } && echo "agent hit the ${AGENT_T}s budget (recorded, not fatal)"
  REWARD=null; VRC=""
  if [ -n "$TDIR" ]; then
    # tests enter the container only now, after the agent is done, so the agent can never read them (Harbor does the same)
    stage verify "$TASKNAME  tests/test.sh  timeout=${VERIF_T}s"
    proxy_phase verify   # the verifier may install its own deps; still logged, never refused
    docker cp "$TDIR/tests/." "$CUR_RUN:/tests/"
    set +e
    with_timeout "$VERIF_T" docker exec -w "$WORKDIR" "$CUR_RUN" bash -lc "${PRELUDE}bash /tests/test.sh" > "$OUT/verifier/stdout.log" 2> "$OUT/verifier/stderr.log"
    VRC=$?; set -e
    REWARD="$(tr -d '[:space:]' < "$OUT/verifier/reward.txt" 2>/dev/null || true)"; REWARD="${REWARD:-null}"
    echo "reward=$REWARD  (verifier rc=$VRC)"
  fi
  finish_containers
  # run.json, result half: merged into the origin written above
  python3 - "$OUT" "$RC" "$SECS" "$REWARD" "$VRC" <<'PY'
import collections, json, sys, os, time
out, rc, secs, reward, vrc = sys.argv[1:]
def interception(out):
    """egress + policy totals for run.json, from egress.jsonl and the flags/rewrites in calls.jsonl."""
    eg = [json.loads(l) for l in open(f"{out}/egress.jsonl")] if os.path.exists(f"{out}/egress.jsonl") else []
    agent = [e for e in eg if e.get("phase") == "agent" and e.get("rule") != "self"]
    hosts = collections.Counter((e["host"], bool(e.get("allowed"))) for e in agent)
    flags = collections.Counter(f["rule"] for c in calls for f in c.get("flags") or [])
    return {"egress": {"connections": len(agent), "blocked": sum(1 for e in agent if not e.get("allowed")),
                       "tls_failed": sum(1 for e in agent if e.get("kind") == "tls"), "verify_phase": sum(1 for e in eg if e.get("phase") == "verify"),
                       "hosts": [{"host": h, "allowed": a, "n": n} for (h, a), n in sorted(hosts.items())]},
            "flags": dict(sorted(flags.items())), "rewrites": sum(len(c.get("rewrites") or []) for c in calls)}
calls = [json.loads(l) for l in open(f"{out}/calls.jsonl")] if os.path.exists(f"{out}/calls.jsonl") else []
rec = json.load(open(f"{out}/run.json"))
rec.update({"finished": time.strftime("%Y-%m-%dT%H:%M:%S"), "rc": int(rc), "seconds": int(secs), "reward": json.loads(reward),
            "verifier_rc": int(vrc) if vrc else None, "calls": len(calls),
            "input_tokens": sum(c["usage"].get("input_tokens") or 0 for c in calls), "output_tokens": sum(c["usage"].get("output_tokens") or 0 for c in calls),
            "errors": sum(1 for c in calls if c.get("error")),
            **interception(out),
            "models": [{"requested": r, "served": s, "calls": n} for (r, s), n in
                       sorted(collections.Counter((c.get("model_requested"), c.get("model")) for c in calls).items(), key=str)],
            "files": sorted(os.listdir(out))})
json.dump(rec, open(f"{out}/run.json", "w"), indent=2)
print(f"rc={rc}  {secs}s  model calls={len(calls)} (in={rec['input_tokens']} out={rec['output_tokens']} tokens, {rec['errors']} errors)" + (f"  reward={reward}" if rec["kind"] == "harbor" else ""))
e = rec["egress"]; print(f"egress: {e['connections']} connections, {e['blocked']} blocked" + (f", {e['tls_failed']} refused interception" if e["tls_failed"] else "")
      + (f"   flags: {rec['flags']}" if rec["flags"] else "") + (f"   rewrites: {rec['rewrites']}" if rec["rewrites"] else ""))
if not calls: print("WARNING: no model calls reached the proxy (check stderr.log and the env in recipe.json)", file=sys.stderr)
PY
}

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
  if ! TIMG="$(task_image "$TDIR" "$TS_NAME" "$TASKNAME")"; then echo "task image failed for $TASKNAME; see work/$NAME/task-build.log"; INFRA_FAIL=1; continue; fi
  OTAG="$(overlay_tag "$TASKNAME")"
  if ! ERR="$(build_overlay "$TIMG" "$OTAG" "$FORCE" 2>&1)"; then echo "$ERR"; echo "overlay failed for $TASKNAME (recorded, skipping)"; INFRA_FAIL=1; continue; fi
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
python3 - "$BATCH" "$K" <<'PY'
import json, sys, collections
rows = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]; k = int(sys.argv[2])
by = collections.OrderedDict()
for r in rows: by.setdefault(r["task"], {})[r["k"]] = r
w = max([len(t) for t in by] + [4])
print(f"{'task':<{w}}  " + "  ".join(f"k{i}" for i in range(1, k + 1)) + "   pass")
tot = ok = 0; allpass = 0
for t, ks in by.items():
    cells = []; n = 0
    for i in range(1, k + 1):
        r = ks.get(i); v = r["reward"] if r else None
        cells.append(" -" if v is None else f"{v:>2}" if isinstance(v, int) else f"{v:.1f}")
        if v is not None: tot += 1; n += 1 if v else 0
    ok += n; allpass += 1 if n == k else 0
    print(f"{t:<{w}}  " + "  ".join(cells) + f"   {n}/{k}")
print(f"\nrewarded runs {ok}/{tot}   tasks passing all k {allpass}/{len(by)}")
PY
echo "runs:  runs/$RUN_ID-<task>$([ "$K" -gt 1 ] && echo "-k<i>")/  (run.json task.txt command.sh recipe.json calls.jsonl stdout.log stderr.log proxy.log verifier/)   list: ./run.sh runs --grep $RUN_ID"
echo "view:  ./run.sh view runs/$RUN_ID-<task>$([ "$K" -gt 1 ] && echo "-k<i>")"
exit "$INFRA_FAIL"
