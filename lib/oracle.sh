# oracle.sh — `run.sh oracle <taskset> <task,...>`: does the task's own reference solution pass its own tests?
# The same task image and the same tests/test.sh a harness run gets, with solution/solve.sh standing in for the
# agent: no proxy, no model, no harness.  A task the site offers must pass this first — a task whose oracle scores
# 0 would report every harness as failing, and that is the environment's fault, not theirs.  Sourced by run.sh.
#
# Each result is one line appended to catalog/oracle.jsonl, {taskset, task, reward, seconds, platform, image, at},
# which lib/tasks.py reads when it publishes the task cards (`runnable` = listed in catalog/runnable.json AND
# the newest oracle line for it says reward 1).

cmd_oracle() {
  local TS="${1:?usage: run.sh oracle <taskset> <task,...>}" NAMES="${2:?usage: run.sh oracle <taskset> <task,...>}"
  PLATFORM="${HR_PLATFORM:-linux/amd64}"; T0=$(date +%s)
  docker info >/dev/null 2>&1 || die "Docker is not running"
  local TSD TS_NAME t TDIR TIMG C S0 RC REWARD VERIF_T WORKDIR OUT="$HERE/catalog/oracle.jsonl" FAIL=0
  TSD="$(taskset_dir "$TS")"; TS_NAME="$(basename "$TSD" | tr 'A-Z' 'a-z' | tr -c 'a-z0-9_.\n-' '-')"
  WORK="$HERE/work/oracle"; mkdir -p "$WORK" "$HERE/catalog"
  IFS=, read -r -a WANT <<< "$NAMES"
  for t in "${WANT[@]}"; do
    TDIR="$TSD/$t"; REWARD=null; RC=""
    stage oracle "$TS_NAME/$t"
    if [ ! -f "$TDIR/task.toml" ]; then echo "no task '$t' in $TSD"; FAIL=1; continue; fi
    if [ ! -f "$TDIR/solution/solve.sh" ]; then echo "no solution/solve.sh"; REWARD=nosolution
    elif ! TIMG="$(task_image "$TDIR" "$TS_NAME" "$t")"; then echo "task image failed; see work/oracle/task-build.log"; REWARD=noimage
    elif task_compose "$TDIR"; then
      S0=$(date +%s)
      local HB_OUT="$WORK/harbor-$t-$(date +%s)-$$"
      mkdir -p "$HB_OUT"
      if harbor_oracle "$TDIR" "$TIMG" "$HB_OUT"; then RC=0; else RC=$?; fi
      REWARD="$(python3 - "$HB_OUT/harbor-result.json" <<'PY'
import json,sys
try: print(json.dumps(json.load(open(sys.argv[1])).get('reward')))
except OSError: print('null')
PY
)"
    else
      IFS='|' read -r _ _ _ VERIF_T _ _ _ _ < <(task_meta "$TDIR")
      WORKDIR="$(docker image inspect -f '{{.Config.WorkingDir}}' "$TIMG")"; WORKDIR="${WORKDIR:-/app}"
      C="hr-oracle-$$-$(printf '%s' "$t" | tr -c 'a-zA-Z0-9_.-' '-' | cut -c1-40)"
      docker rm -f "$C" >/dev/null 2>&1 || true
      docker run -d --platform "$PLATFORM" --name "$C" -w "$WORKDIR" -e TEST_DIR=/tests "$TIMG" sleep infinity >/dev/null
      docker exec "$C" mkdir -p /logs/verifier /logs/agent /solution /tests
      docker cp "$TDIR/solution/." "$C:/solution/"
      S0=$(date +%s); set +e
      with_timeout 1800 docker exec -w "$WORKDIR" "$C" bash -lc "bash /solution/solve.sh" > "$WORK/$t.solve.log" 2>&1
      docker cp "$TDIR/tests/." "$C:/tests/"
      with_timeout "$VERIF_T" docker exec -w "$WORKDIR" "$C" bash -lc "bash /tests/test.sh" > "$WORK/$t.verify.log" 2>&1
      RC=$?; set -e
      REWARD="$(docker exec "$C" cat /logs/verifier/reward.txt 2>/dev/null | tr -d '[:space:]' || true)"; REWARD="${REWARD:-null}"
      docker rm -f "$C" >/dev/null 2>&1 || true
    fi
    echo "oracle $TS_NAME/$t  reward=$REWARD  verifier rc=${RC:-none}  $(( $(date +%s) - ${S0:-$(date +%s)} ))s   (logs: work/oracle/$t.*.log)"
    case "$REWARD" in 1|1.0) ;; *) FAIL=1 ;; esac
    python3 - "$OUT" "$TS_NAME" "$t" "$REWARD" "$(( $(date +%s) - ${S0:-$(date +%s)} ))" "$PLATFORM" "${TIMG:-}" <<'EOF'
import json, sys, time
out, ts, t, reward, secs, platform, image = sys.argv[1:]
try: reward = float(reward); reward = int(reward) if reward.is_integer() else reward
except ValueError: pass
with open(out, "a") as f:
    f.write(json.dumps({"taskset": ts, "task": t, "reward": reward, "seconds": int(secs), "platform": platform,
                        "image": image, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}) + "\n")
EOF
    unset S0 TIMG
  done
  return "$FAIL"
}

# Separate network and process-scoped teardown; never alters the task or candidate list.
harbor_oracle() (
  local task="$1" image="$2" out="$3" net="hr-oracle-$$-$RANDOM"
  docker network create "$net" >/dev/null || exit 1
  trap 'docker network rm "$net" >/dev/null 2>&1 || true' EXIT
  trap 'exit 143' TERM INT
  local wd; wd="$(docker image inspect -f '{{.Config.WorkingDir}}' "$image")"
  harbor_backend run --oracle --task "$task" --image "$image" --out "$out" --work "$out/work" \
    --workdir "${wd:-/app}" --platform "$PLATFORM" --network "$net" --verify-network "$net" --egress open \
    > "$out/oracle.log" 2>&1
)
