#!/usr/bin/env bash
# run.sh — give it a GitHub repo and a task; it downloads the repo, has an AI write a sandbox for it, builds the
# sandbox, puts a recording proxy between the harness and the model, and runs the task.
#
#   ./run.sh <github-url> "<task text>"     the whole thing
#   ./run.sh <github-url> --task-file f      task from a file (or pipe it on stdin)
#   ./run.sh view runs/<name>/<run-id>       print the recorded model calls as a conversation
#
#   --rebuild    ignore the saved recipe/image for this repo and let the AI generate the sandbox again
#   --run-id ID  name the run (default: timestamp)
#
# Stages:   fetch     git clone → work/<name>/repo
#           analyze   claude -p reads the repo and returns a recipe: Dockerfile, env that points the harness at the
#                     proxy, the command that runs one task ($TASK), a check command   → work/<name>/recipe.json
#           build     docker build the sandbox image hr-<name>; on failure the error goes back to the AI (3 tries)
#           proxy     start proxy.py (OpenAI + Anthropic API in, Bedrock out) with ~/.aws; the harness never sees creds
#           run       docker run the sandbox with $TASK; every model call lands in runs/<name>/<run-id>/calls.jsonl
#
# .env holds MODEL (bedrock/<model-id>), AWS_PROFILE, AWS_REGION.  ANALYZER_MODEL picks the claude -p model.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
die() { echo "run.sh: $*" >&2; exit 2; }
[ $# -gt 0 ] || { sed -n '2,20p' "$0"; exit 0; }

# ------------------------------------------------------------------ view
if [ "${1:-}" = view ]; then
  D="${2:?usage: run.sh view runs/<name>/<run-id>}"; [ -f "$D/calls.jsonl" ] || D="$(dirname "$D")"
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
URL=""; TASK=""; TASK_FILE=""; REBUILD=0; RUN_ID=""
while [ $# -gt 0 ]; do
  case "$1" in
    --rebuild) REBUILD=1 ;;
    --run-id) RUN_ID="${2:?}"; shift ;;
    --task-file) TASK_FILE="${2:?}"; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    --*) die "unknown option $1" ;;
    *) if [ -z "$URL" ]; then URL="$1"; elif [ -z "$TASK" ]; then TASK="$1"; else die "unexpected argument: $1"; fi ;;
  esac; shift
done
[ -n "$URL" ] || die "usage: run.sh <github-url> \"<task>\""
[ -n "$TASK_FILE" ] && TASK="$(cat "$TASK_FILE")"
[ -n "$TASK" ] || { [ -t 0 ] || TASK="$(cat)"; }
[ -n "$TASK" ] || die "no task given"
[ -f "$HERE/.env" ] || die "no .env (MODEL, AWS_PROFILE, AWS_REGION)"
set -a; . "$HERE/.env"; set +a
: "${MODEL:?MODEL in .env}"; : "${AWS_PROFILE:?AWS_PROFILE in .env}"; AWS_REGION="${AWS_REGION:-us-west-2}"
docker info >/dev/null 2>&1 || die "Docker is not running"
command -v claude >/dev/null || die "claude CLI not found (the analyze stage runs claude -p)"

[[ "$URL" =~ github\.com[/:]([^/[:space:]]+)/([^/[:space:]#?]+) ]] || die "not a GitHub URL: $URL"
OWNER="${BASH_REMATCH[1]}"; REPO="${BASH_REMATCH[2]%.git}"
NAME="$(printf '%s-%s' "$OWNER" "$REPO" | tr 'A-Z' 'a-z' | tr -c 'a-z0-9.-\n' '-')"
WORK="$HERE/work/$NAME"; SRC="$WORK/repo"; RECIPE="$WORK/recipe.json"; IMAGE="hr-$NAME"
RUN_ID="${RUN_ID:-$(date +%Y%m%dT%H%M%S)}"; OUT="$HERE/runs/$NAME/$RUN_ID"; mkdir -p "$OUT" "$WORK"
T0=$(date +%s); stage() { echo; echo "━━ [$1] $(( $(date +%s) - T0 ))s  ${2:-}"; }
printf '%s\n' "$TASK" > "$OUT/task.txt"
echo "repo   https://github.com/$OWNER/$REPO   →   $NAME"
echo "task   $TASK"
echo "model  $MODEL   (via proxy)"
echo "out    runs/$NAME/$RUN_ID/"

# ------------------------------------------------------------------ 1. fetch
stage fetch "git clone → work/$NAME/repo"
if [ -d "$SRC/.git" ] && [ "$REBUILD" = 0 ]; then echo "already cloned ($(git -C "$SRC" rev-parse --short HEAD)); --rebuild to re-clone"
else rm -rf "$SRC"; git clone -q --depth 1 "https://github.com/$OWNER/$REPO" "$SRC"; echo "cloned $(git -C "$SRC" rev-parse --short HEAD)"; fi
printf '{"repo":"https://github.com/%s/%s","commit":"%s"}\n' "$OWNER" "$REPO" "$(git -C "$SRC" rev-parse HEAD)" > "$WORK/source.json"

# ------------------------------------------------------------------ 2+3. analyze (AI) and build, with the build error fed back
SCHEMA='{"type":"object","required":["summary","dockerfile","run_command","check_command","env","api_style"],"properties":{
 "summary":{"type":"string","description":"one paragraph: what the harness is, its entrypoint, how it calls the model"},
 "dockerfile":{"type":"string","description":"complete Dockerfile; build context is the repo root"},
 "run_command":{"type":"string","description":"bash, run inside the container, runs ONE task from $TASK non-interactively and exits"},
 "check_command":{"type":"string","description":"bash, verifies the install without calling a model (e.g. the CLI --help)"},
 "env":{"type":"array","items":{"type":"object","required":["name","value"],"properties":{"name":{"type":"string"},"value":{"type":"string"}}},
        "description":"environment for the run: routes the harness model calls to $PROXY_URL (literal placeholder), picks the model name, disables wizards/prompts"},
 "api_style":{"type":"string","enum":["openai","anthropic"],"description":"which API the harness will speak to the proxy"},
 "workdir":{"type":"string","description":"working directory inside the container for the task (default /work)"},
 "notes":{"type":"string"}}}'

analyze() {  # $1 = feedback from a failed build/check, or empty
  local tree; tree="$(cd "$SRC" && find . -maxdepth 2 -not -path './.git*' -not -path './node_modules*' | sort | head -150)"
  local prompt
  prompt="You are packaging the AI agent harness in the current directory (a fresh clone of https://github.com/$OWNER/$REPO) so it can run ONE task inside a Docker sandbox, with all its model calls going through a recording proxy. Read the repo (README, manifests, the CLI entrypoint, the model/provider client code) and return the recipe as JSON matching the schema.

THE PROXY CONTRACT
- The proxy is reachable from the container at \$PROXY_URL (literal string; it is substituted at run time). It speaks BOTH
  the OpenAI chat-completions API (\$PROXY_URL/v1/chat/completions, list at \$PROXY_URL/v1/models) and the Anthropic
  messages API (\$PROXY_URL/v1/messages). Streaming and tool calling work on both. Any API key string is accepted.
- Whatever model name the harness sends is replaced by the real model on the far side, so pick a model name the harness
  accepts without complaint locally (e.g. for litellm use an 'openai/<name>' or 'anthropic/<name>' prefix so the base URL
  applies; for the OpenAI SDK any name; for the Anthropic SDK a claude name).
- The harness must NOT need any cloud credentials or network access other than the proxy at run time.
  Typical env: OPENAI_BASE_URL=\$PROXY_URL/v1 + OPENAI_API_KEY=proxy, or ANTHROPIC_BASE_URL=\$PROXY_URL + ANTHROPIC_API_KEY=proxy,
  plus whatever variable this harness uses to choose the model, plus anything that skips first-run wizards, telemetry,
  confirmations, or interactive prompts (stdin is NOT a tty).

THE DOCKERFILE
- Build context is the repo root: COPY the source in (e.g. to /harness) and install it there so the entrypoint works.
- Pick a sensible official base image for the language; install system packages the harness needs; make sure bash exists.
- Do not bake in secrets. Do not run the harness during the build. The harness is never modified.

THE RUN COMMAND
- bash, run inside the container with the env above and the task text in \$TASK. It must run exactly one task
  non-interactively through the harness's own CLI entrypoint and exit when done. If the harness can write its own
  trajectory/log/history to a path, write it under /out/ (mounted from the host). Use \$TASK unquoted-safe: e.g. -t \"\$TASK\".
- check_command: something fast that proves the install works without calling a model (e.g. the CLI --help).

Repository tree (2 levels):
$tree"
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
import json, sys
raw, recipe, dockerfile = sys.argv[1:]
d = json.load(open(raw))
so = d.get("structured_output")
if not so: sys.exit(f"analyze: no structured output (subtype={d.get('subtype')}, result={str(d.get('result'))[:300]})")
json.dump(so, open(recipe, "w"), indent=2)
open(dockerfile, "w").write(so["dockerfile"].rstrip() + "\n")
print(f"recipe: api={so['api_style']}  env={' '.join(e['name'] for e in so['env'])}  cost=${d.get('total_cost_usd', 0):.2f}  turns={d.get('num_turns')}")
print("summary: " + so["summary"].strip().replace("\n", " ")[:600])
print("run_command: " + so["run_command"].strip())
PY
}
build() {  # docker build + check command; prints the error on failure
  docker build -q -t "$IMAGE" -f "$WORK/Dockerfile" "$SRC" > "$WORK/build.log" 2>&1 || { tail -40 "$WORK/build.log"; return 1; }
  echo "image $IMAGE built"
  local chk; chk="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["check_command"])' "$RECIPE")"
  echo "check: $chk"
  docker run --rm --network none "$IMAGE" bash -lc "$chk" > "$WORK/check.log" 2>&1 || { tail -40 "$WORK/check.log"; return 1; }
  echo "check passed"
}

if [ "$REBUILD" = 0 ] && [ -f "$RECIPE" ] && docker image inspect "$IMAGE" >/dev/null 2>&1; then
  stage analyze "recipe exists: work/$NAME/recipe.json (--rebuild to regenerate)"
  python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); print("api="+r["api_style"]+"  run_command: "+r["run_command"].strip())' "$RECIPE"
  stage build "image $IMAGE exists"
else
  FEEDBACK=""; OK=0
  for attempt in 1 2 3; do
    stage analyze "attempt $attempt: claude -p reads the repo and writes the recipe (work/$NAME/{recipe.json,Dockerfile})"
    analyze "$FEEDBACK" || { FEEDBACK="the analyzer returned no recipe"; continue; }
    stage build "docker build -t $IMAGE"
    if ERR="$(build 2>&1)"; then echo "$ERR"; OK=1; break; else echo "$ERR"; FEEDBACK="$ERR"; fi
  done
  [ "$OK" = 1 ] || die "could not build a working sandbox after 3 attempts; see work/$NAME/{build.log,check.log,analyze.stderr}"
fi
cp "$RECIPE" "$OUT/recipe.json"

# ------------------------------------------------------------------ 4. proxy
stage proxy "proxy.py on the hr-net network, model=$MODEL"
docker network inspect hr-net >/dev/null 2>&1 || docker network create hr-net >/dev/null
PROXY_IMG="hr-proxy"; PCTX="$WORK/.proxy-ctx"; mkdir -p "$PCTX"; cp "$HERE/proxy.py" "$PCTX/"
printf 'FROM python:3.12-slim\nRUN pip install -q --root-user-action=ignore boto3\nCOPY proxy.py /proxy.py\nCMD ["python3","-u","/proxy.py"]\n' > "$PCTX/Dockerfile"
docker build -q -t "$PROXY_IMG" "$PCTX" >/dev/null
PROXY="hr-proxy-$RUN_ID"
docker rm -f "$PROXY" >/dev/null 2>&1 || true
docker run -d --name "$PROXY" --network hr-net -v "$HOME/.aws:/root/.aws:ro" -v "$OUT:/out" \
  -e "MODEL=$MODEL" -e "AWS_PROFILE=$AWS_PROFILE" -e "AWS_REGION=$AWS_REGION" -e "AWS_DEFAULT_REGION=$AWS_REGION" -e LOG=/out/calls.jsonl \
  "$PROXY_IMG" >/dev/null
cleanup() { docker logs "$PROXY" > "$OUT/proxy.log" 2>&1 || true; docker rm -f "$PROXY" >/dev/null 2>&1 || true; }
trap cleanup EXIT
for i in $(seq 1 30); do
  docker exec "$PROXY" python3 -c "import urllib.request;urllib.request.urlopen('http://localhost:4000/health',timeout=2)" 2>/dev/null && break
  sleep 1; [ "$i" = 30 ] && { docker logs "$PROXY"; die "proxy did not come up"; }
done
echo "proxy up: http://$PROXY:4000 (inside hr-net)   recording → runs/$NAME/$RUN_ID/calls.jsonl"

# ------------------------------------------------------------------ 5. run
PROXY_URL="http://$PROXY:4000"
ENV_ARGS=(); while IFS= read -r kv; do ENV_ARGS+=(-e "$kv"); done < <(
  PROXY_URL="$PROXY_URL" python3 -c 'import json,os,sys
for e in json.load(open(sys.argv[1]))["env"]: print(e["name"]+"="+e["value"].replace("$PROXY_URL", os.environ["PROXY_URL"]).replace("${PROXY_URL}", os.environ["PROXY_URL"]))' "$RECIPE")
RUN_CMD="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["run_command"])' "$RECIPE")"
WORKDIR="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("workdir") or "/work")' "$RECIPE")"
stage run "$RUN_CMD"
printf '%s\n' "$RUN_CMD" > "$OUT/command.sh"
START=$(date +%s); set +e
docker run --rm --name "hr-run-$RUN_ID" --network hr-net -v "$OUT:/out" -w "$WORKDIR" \
  -e "TASK=$TASK" -e "PROXY_URL=$PROXY_URL" "${ENV_ARGS[@]}" "$IMAGE" \
  bash -lc "mkdir -p $WORKDIR && cd $WORKDIR && $RUN_CMD" 2>"$OUT/stderr.log" | tee "$OUT/stdout.log"
RC=${PIPESTATUS[0]}; set -e
SECS=$(( $(date +%s) - START ))
CALLS=$( [ -f "$OUT/calls.jsonl" ] && wc -l < "$OUT/calls.jsonl" | tr -d ' ' || echo 0 )
python3 - "$OUT" "$NAME" "$RUN_ID" "$MODEL" "$RC" "$SECS" "$OWNER/$REPO" "$(git -C "$SRC" rev-parse HEAD)" <<'PY'
import json, sys, os
out, name, run_id, model, rc, secs, repo, commit = sys.argv[1:]
calls = [json.loads(l) for l in open(f"{out}/calls.jsonl")] if os.path.exists(f"{out}/calls.jsonl") else []
rec = {"name": name, "run": run_id, "repo": "https://github.com/" + repo, "commit": commit, "model": model, "rc": int(rc), "seconds": int(secs),
       "task": open(f"{out}/task.txt").read().strip(), "calls": len(calls),
       "input_tokens": sum(c["usage"].get("input_tokens") or 0 for c in calls), "output_tokens": sum(c["usage"].get("output_tokens") or 0 for c in calls),
       "errors": sum(1 for c in calls if c.get("error")), "files": sorted(os.listdir(out))}
json.dump(rec, open(f"{out}/run.json", "w"), indent=2)
print(f"\nrc={rc}  {secs}s  model calls={len(calls)} (in={rec['input_tokens']} out={rec['output_tokens']} tokens, {rec['errors']} errors)")
PY
echo "done in $(( $(date +%s) - T0 ))s   runs/$NAME/$RUN_ID/   (task.txt command.sh calls.jsonl stdout.log stderr.log proxy.log run.json recipe.json)"
echo "view:  ./run.sh view runs/$NAME/$RUN_ID"
[ "$CALLS" -gt 0 ] || { echo "WARNING: no model calls reached the proxy (check stderr.log and the env in recipe.json)" >&2; }
exit "$RC"
