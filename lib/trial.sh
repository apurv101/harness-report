#!/usr/bin/env bash
# trial.sh — the recipe agent's hands (lib/recipe_agent.py): build a candidate recipe, run the harness from it against
# the recording proxy, or run one command in an image.  Each goes through the functions run.sh itself uses —
# build_overlay and check_image, build_proxy_image and start_proxy, agent_phase — so a recipe the agent proved here is
# built and started the same way by the pipeline.  The machine is this one's Docker.
#
#   trial.sh build <recipe.json> <src> <commit> <base-image> <tag> <dir>     overlay FROM base-image, then its check
#   trial.sh run <recipe.json> <image> <workdir> <instruction> <out> <seconds> [<harbor-task-dir>]
#                                                                           run-harness through the proxy, no verifier
#   trial.sh exec <image> <none|open> <seconds> <command>                    the command in a fresh container
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
. "$HERE/lib/common.sh"; . "$HERE/lib/recipe.sh"; . "$HERE/lib/proxy.sh"; . "$HERE/lib/execute.sh"
[ -f "$HERE/.env" ] && eval "$(python3 "$HERE/lib/dotenv.py" "$HERE/.env")"
PLATFORM="${HR_PLATFORM:-linux/amd64}"; T0=$(date +%s)
JOB_LABEL=(); [ -z "${HR_LOCAL_EVAL_ID:-}" ] || JOB_LABEL=(--label "hr.evaluation=$HR_LOCAL_EVAL_ID")
HR_EVENTS=""   # a trial is not a stage of the run the site is following

case "${1:-}" in
  build)
    RECIPE="$2" SRC="$3" COMMIT="$4" WORK="$7"; mkdir -p "$WORK"
    recipe_field dockerfile > "$WORK/Dockerfile"
    build_overlay "$5" "$6" 1 ;;
  run)
    RECIPE="$2" OTAG="$3" WORKDIR="$4" INSTR="$5" OUT="$6" AGENT_T="$7" TDIR="${8:-}"
    RUN="trial-$(basename "$OUT")-$$"; RUN_ID="$RUN"; TASKNAME=trial
    WORK="$OUT/.trial"; WRAPPER="$WORK/run-harness"; mkdir -p "$WORK"; RES_ARGS=()
    : "${MODEL:?MODEL in .env}"; ROUTES="${ROUTES:-}"; AWS_REGION="${AWS_REGION:-us-west-2}"
    EGRESS="${EGRESS:-record}"; POLICY="${POLICY:-flag}"; BLOCK_URLS="${BLOCK_URLS:-}"
    RUN_CMD="$(recipe_field run_command)"
    write_wrapper
    build_proxy_image
    trap finish_containers EXIT
    start_proxy "$(proxy_name "$RUN")" "$OUT"
    agent_phase
    # what the harness changed in its container: the evidence that it acted on the task, not just started
    docker diff "$CUR_RUN" > "$OUT/changes.txt" 2>/dev/null || true
    finish_containers
    echo "rc=$RC seconds=$SECS" ;;
  exec)
    name="hr-trial-exec-$$"; net=(--network none); [ "$3" = open ] && net=()
    trap 'docker rm -f "$name" >/dev/null 2>&1 || true' EXIT
    with_timeout "$4" docker run --name "$name" --platform "$PLATFORM" ${net[@]+"${net[@]}"} \
      -e "HR_PATH=$(image_path "$2" 2>/dev/null || true)" "$2" bash -lc "$PRELUDE$5" 2>&1 ;;
  *) echo "usage: trial.sh build|run|exec ..." >&2; exit 2 ;;
esac
